from decimal import Decimal
import json

import pytest

from foundry.analysis import AnalysisStore
from foundry.cli import main
from foundry.errors import FoundryError
from foundry.task import TaskStore


@pytest.fixture
def work(tmp_path):
    task = TaskStore(tmp_path / "var").create(title="回款分析")
    store = AnalysisStore(task)
    source = tmp_path / "actual.json"
    source.write_text('[{"region":"PrivateClient","amount":100}]')
    data = store.add_dataset(
        source,
        name="实际",
        metadata={"period": "2026-08", "currency": "CNY", "unit": "万元"},
    )
    return store, data


def spec(data, **fields):
    return {
        "question": "测算回款",
        "sql": "SELECT amount*CAST($rate AS DECIMAL(38,2)) AS expected FROM actual WHERE region=$region",
        "bindings": {"actual": data["id"]},
        "parameters": {"rate": "0.85", "region": "PrivateClient"},
        **fields,
    }


def metadata():
    return [
        {
            "key": "rate",
            "label": "预计回款率",
            "type": "decimal",
            "unit": "比例",
            "description": "测算口径",
            "constraints": {"min": "0", "max": "1"},
        },
        {"key": "region", "label": "地区", "type": "string"},
    ]


def test_optional_metadata_preserves_explicit_business_contract(work):
    service, data = work
    revision = service.save_analysis(spec(data, parameter_metadata=metadata()))
    assert revision["parameter_metadata"][0]["key"] == "rate"
    assert revision["parameter_metadata"][0]["label"] == "预计回款率"
    assert revision["parameter_metadata"][0]["role"] == "business"
    run = service.run_analysis(revision["id"])
    assert run["execution_status"] == "succeeded"
    assert Decimal(run["result"]["rows"][0]["expected"]) == 85
    assert service.read_dataset(data["id"])["metadata"] == {
        "period": "2026-08",
        "currency": "CNY",
        "unit": "万元",
    }


def test_without_metadata_does_not_infer_labels_or_change_parameters(work):
    service, data = work
    revision = service.save_analysis(spec(data))
    assert revision.get("parameter_metadata", []) == []
    assert revision["parameters"] == {"rate": "0.85", "region": "PrivateClient"}


@pytest.mark.parametrize(
    "entry",
    [
        {"key": "not_in_sql", "label": "x", "type": "decimal"},
        {"key": "rate", "position": 1, "label": "x", "type": "decimal"},
        {"position": 0, "label": "x", "type": "decimal"},
        {"position": True, "label": "x", "type": "decimal"},
        {"key": "rate", "label": "", "type": "decimal"},
        {"key": "rate", "label": "x", "type": "invented"},
        {
            "key": "rate",
            "label": "x",
            "type": "decimal",
            "constraints": {"minimum": "0"},
        },
        {
            "key": "rate",
            "label": "x",
            "type": "decimal",
            "constraints": {"min": "2", "max": "1"},
        },
        {"key": "rate", "label": "x", "type": "decimal", "role": "formula_constant"},
        {
            "key": "region",
            "label": "地区",
            "type": "string",
            "role": "formula_constant",
            "default": "PrivateClient",
        },
    ],
)
def test_invalid_metadata_is_refused_before_revision_write(work, entry):
    service, data = work
    before = service.state()["analyses"]
    with pytest.raises(FoundryError, match="parameter"):
        service.save_analysis(spec(data, parameter_metadata=[entry]))
    assert service.state()["analyses"] == before


def test_duplicate_and_out_of_range_business_bindings_refused(work):
    service, data = work
    with pytest.raises(FoundryError, match="duplicate"):
        service.save_analysis(
            spec(data, parameter_metadata=[metadata()[0], metadata()[0]])
        )
    with pytest.raises(FoundryError, match="max"):
        service.save_analysis(
            spec(
                data,
                parameters={"rate": "1.1", "region": "PrivateClient"},
                parameter_metadata=metadata(),
            )
        )
    with pytest.raises(FoundryError, match="parameter"):
        service.save_analysis(
            spec(
                data,
                parameters={"rate": "NaN", "region": "PrivateClient"},
                parameter_metadata=metadata(),
            )
        )


def test_position_is_one_based_and_named_parameters_need_keys(work):
    service, data = work
    positional = service.save_analysis(
        spec(
            data,
            sql="SELECT amount*CAST(? AS DECIMAL(38,2)) FROM actual",
            parameters=["0.85"],
            parameter_metadata=[{"position": 1, "label": "回款率", "type": "decimal"}],
        )
    )
    assert positional["parameter_metadata"][0]["key"] == "1"
    assert "position" not in positional["parameter_metadata"][0]
    with pytest.raises(FoundryError, match="parameter"):
        service.save_analysis(
            spec(
                data,
                parameter_metadata=[
                    {"position": 1, "label": "回款率", "type": "decimal"}
                ],
            )
        )


def test_metadata_revision_does_not_change_previous_parameter_value(work):
    service, data = work
    first = service.save_analysis(spec(data, parameter_metadata=metadata()))
    oldrun = service.run_analysis(first["id"])
    following = service.save_analysis(
        spec(
            data,
            parent_id=first["id"],
            parameters={"rate": "0.9", "region": "PrivateClient"},
            parameter_metadata=metadata(),
        )
    )
    assert service.get_analysis(first["id"])["parameters"]["rate"] == "0.85"
    assert service.get_run(oldrun["id"])["parameters"]["rate"] == "0.85"
    assert (
        Decimal(service.run_analysis(following["id"])["result"]["rows"][0]["expected"])
        == 90
    )


def test_method_metadata_preserves_binding_and_removes_business_defaults_choices(
    work, tmp_path
):
    service, data = work
    fields = metadata()
    fields[1].update(
        default="PrivateClient",
        constraints={"choices": ["PrivateClient", "PrivateOther"]},
    )
    revision = service.save_analysis(spec(data, parameter_metadata=fields))
    method = service.save_method(revision["id"], "回款测算")
    assert "PrivateClient" not in json.dumps(
        method
    ) and "PrivateOther" not in json.dumps(method)
    mapped = {
        row["source_parameter"]: row
        for row in method["parameter_contract"]
        if row["source"] == "parameter"
    }
    assert mapped["rate"]["metadata"]["label"] == "预计回款率"
    assert mapped["rate"]["metadata"]["key"] == mapped["rate"]["parameter"]
    assert "default" not in mapped["region"]["metadata"]
    assert "choices" not in mapped["region"]["metadata"].get("constraints", {})
    other = AnalysisStore(service.task.store.create(title="新任务"))
    source = tmp_path / "next.json"
    source.write_text('[{"region":"NewRegion","amount":200}]')
    newdata = other.add_dataset(source, name="新资料")
    parameters = {
        mapped["rate"]["parameter"]: "0.75",
        mapped["region"]["parameter"]: "NewRegion",
    }
    applied = other.apply_method(
        method["id"], {"actual": newdata["id"]}, parameters=parameters
    )
    assert applied["parameter_metadata"][0]["label"] == "预计回款率"
    assert (
        Decimal(other.run_analysis(applied["id"])["result"]["rows"][0]["expected"])
        == 150
    )


def test_safe_structural_formula_defaults_and_business_input(work):
    service, data = work
    query = "SELECT SUM(CASE WHEN region=$region THEN amount ELSE 0 END)/NULLIF(SUM(amount),0)*100 AS share FROM actual"
    revision = service.save_analysis(
        spec(
            data,
            sql=query,
            parameters={"region": "PrivateClient"},
            parameter_metadata=[metadata()[1]],
        )
    )
    method = service.save_method(revision["id"], "占比")
    constants = [
        row for row in method["parameter_contract"] if row["role"] == "formula_constant"
    ]
    assert sorted(Decimal(row["default"]) for row in constants) == [0, 0, 100]
    business = next(
        row
        for row in method["parameter_contract"]
        if row["source_parameter"] == "region"
    )
    applied = service.apply_method(
        method["id"],
        {"actual": data["id"]},
        parameters={business["parameter"]: "PrivateClient"},
    )
    assert (
        Decimal(service.run_analysis(applied["id"])["result"]["rows"][0]["share"])
        == 100
    )
    with pytest.raises(FoundryError, match="parameter"):
        service.apply_method(method["id"], {"actual": data["id"]}, parameters={})


@pytest.mark.parametrize(
    "query",
    [
        "SELECT amount FROM actual WHERE amount=100",
        "SELECT amount FROM actual LIMIT 100",
        "SELECT SUM(amount+100) FROM actual",
        "SELECT SUM(100) FROM actual",
        "SELECT CAST(100 AS DECIMAL(38,2)) FROM actual",
        "SELECT CASE WHEN amount=100 THEN 100 ELSE 500000 END FROM actual",
        "SELECT amount*500000 FROM actual",
        "SELECT amount+'100' FROM actual",
    ],
)
def test_other_literals_do_not_receive_private_defaults(work, query):
    service, data = work
    revision = service.save_analysis(spec(data, sql=query, parameters=[]))
    method = service.save_method(revision["id"], "方法")
    assert all(
        row["role"] == "unclassified" and "default" not in row
        for row in method["parameter_contract"]
    )
    assert "500000" not in json.dumps(method)


def test_explicit_formula_default_is_declaration_not_copied_actual(work):
    service, data = work
    fields = [
        {
            "key": "factor",
            "label": "百分比换算",
            "type": "integer",
            "role": "formula_constant",
            "default": "100",
        }
    ]
    query = "SELECT amount*CAST($factor AS INTEGER) FROM actual"
    revision = service.save_analysis(
        spec(data, sql=query, parameters={"factor": "100"}, parameter_metadata=fields)
    )
    method = service.save_method(revision["id"], "倍数")
    assert method["parameter_contract"][0]["default"] == "100"
    applied = service.apply_method(method["id"], {"actual": data["id"]}, parameters={})
    assert (
        Decimal(
            next(
                iter(service.run_analysis(applied["id"])["result"]["rows"][0].values())
            )
        )
        == 10000
    )
    with pytest.raises(FoundryError, match="default"):
        service.save_analysis(
            spec(
                data,
                sql=query,
                parameters={"factor": "500000"},
                parameter_metadata=fields,
            )
        )


def test_legacy_method_without_policy_still_applies(work):
    service, data = work
    old = service.save_analysis(spec(data))
    method = service.save_method(old["id"], "旧方法模拟")
    for key in ["parameter_policy_version", "parameter_metadata"]:
        method.pop(key, None)
    for row in method["parameter_contract"]:
        for key in [
            "role",
            "default",
            "source_parameter",
            "metadata",
            "default_strategy",
        ]:
            row.pop(key, None)
    method.pop("_integrity_hash", None)
    method.pop("seq", None)
    import uuid

    method["id"] = uuid.uuid4().hex
    service._write(service._object_path("methods", method["id"]), method)
    applied = service.apply_method(
        method["id"], {"actual": data["id"]}, parameters=["0.85", "PrivateClient"]
    )
    assert applied.get("parameter_metadata", []) == []
    assert service.run_analysis(applied["id"])["execution_status"] == "succeeded"


def test_cli_metadata_contract_and_default_apply(work, capsys):
    service, data = work
    args = ["--var", str(service.task.store.var_root), "--task", service.task.id]
    specification = spec(data, parameter_metadata=metadata())
    assert main([*args, "analysis-save", "--spec", json.dumps(specification)]) == 0
    revision = json.loads(capsys.readouterr().out)
    assert revision["parameter_metadata"][0]["label"] == "预计回款率"


def test_semantic_keys_survive_constant_before_original_parameter(work):
    service, data = work
    query = "SELECT 100*CAST($rate AS DECIMAL(38,2)) AS percent FROM actual WHERE region=$region"
    revision = service.save_analysis(
        spec(data, sql=query, parameter_metadata=metadata())
    )
    method = service.save_method(revision["id"], "比率")
    mapped = {
        entry["source_parameter"]: entry
        for entry in method["parameter_contract"]
        if entry["source"] == "parameter"
    }
    assert mapped["rate"]["parameter"] != "rate"
    assert mapped["rate"]["metadata"]["key"] == mapped["rate"]["parameter"]
    assert mapped["rate"]["metadata"]["label"] == "预计回款率"
    applied = service.apply_method(
        method["id"],
        {"actual": data["id"]},
        parameters={
            mapped["rate"]["parameter"]: "0.6",
            mapped["region"]["parameter"]: "PrivateClient",
        },
    )
    assert (
        Decimal(service.run_analysis(applied["id"])["result"]["rows"][0]["percent"])
        == 60
    )
    saved_again = service.save_method(applied["id"], "二次保存")
    assert any(
        entry["role"] == "formula_constant" and entry["default"] == "100"
        for entry in saved_again["parameter_contract"]
    )


@pytest.mark.parametrize(
    "kind,value,valid",
    [
        ("boolean", True, True),
        ("boolean", "true", False),
        ("integer", "12", True),
        ("integer", "12.1", False),
        ("date", "2026-08-31", True),
        ("date", "2026-02-31", False),
        ("string", "实际", True),
        ("string", 123, False),
    ],
)
def test_declared_business_types_validate_actual_values(work, kind, value, valid):
    service, data = work
    definition = spec(
        data,
        sql="SELECT $value AS value FROM actual",
        parameters={"value": value},
        parameter_metadata=[{"key": "value", "label": "业务字段", "type": kind}],
    )
    if valid:
        assert (
            service.save_analysis(definition)["parameter_metadata"][0]["type"] == kind
        )
    else:
        with pytest.raises(FoundryError, match="parameter"):
            service.save_analysis(definition)


def test_decimal_guard_literals_remain_exact_defaults(work):
    service, data = work
    revision = service.save_analysis(
        spec(
            data,
            sql="SELECT amount/NULLIF(amount,0.00)*100.00 AS share FROM actual",
            parameters=[],
        )
    )
    method = service.save_method(revision["id"], "小数公式")
    assert [entry["default"] for entry in method["parameter_contract"]] == ["0", "100"]
    applied = service.apply_method(method["id"], {"actual": data["id"]})
    assert (
        Decimal(service.run_analysis(applied["id"])["result"]["rows"][0]["share"])
        == 100
    )


def test_cli_apply_omits_formula_default_and_uses_new_business_values(work, capsys):
    service, data = work
    revision = service.save_analysis(
        spec(
            data,
            sql="SELECT CAST($rate AS DECIMAL(38,2))*100 AS percent FROM actual",
            parameters={"rate": "0.85"},
            parameter_metadata=[metadata()[0]],
        )
    )
    method = service.save_method(revision["id"], "新比例")
    parameter = next(
        entry["parameter"]
        for entry in method["parameter_contract"]
        if entry["source_parameter"] == "rate"
    )
    args = ["--var", str(service.task.store.var_root), "--task", service.task.id]
    assert (
        main(
            [
                *args,
                "analysis-method-apply",
                "--method",
                method["id"],
                "--bindings",
                json.dumps({"actual": data["id"]}),
                "--parameters",
                json.dumps({parameter: "0.7"}),
            ]
        )
        == 0
    )
    applied = json.loads(capsys.readouterr().out)
    assert applied["parameter_metadata"][0]["label"] == "预计回款率"
    assert (
        Decimal(service.run_analysis(applied["id"])["result"]["rows"][0]["percent"])
        == 70
    )


def test_near_hundred_is_not_rounded_into_a_formula_default(work):
    service, data = work
    revision = service.save_analysis(
        spec(
            data,
            sql="SELECT amount*100.000000000000000000000000001 FROM actual",
            parameters=[],
        )
    )
    method = service.save_method(revision["id"], "高精度系数")
    assert method["parameter_contract"][0]["role"] == "unclassified"
    assert "default" not in method["parameter_contract"][0]


def test_formula_choice_domains_are_not_shared_with_the_default(work):
    service, data = work
    fields = [
        {
            "key": "factor",
            "label": "比例换算",
            "type": "integer",
            "role": "formula_constant",
            "default": "100",
            "constraints": {"choices": ["100", "777777"]},
        }
    ]
    revision = service.save_analysis(
        spec(
            data,
            sql="SELECT amount*CAST($factor AS INTEGER) FROM actual",
            parameters={"factor": "100"},
            parameter_metadata=fields,
        )
    )
    method = service.save_method(revision["id"], "常数")
    assert "777777" not in json.dumps(method)
    assert method["parameter_contract"][0]["default"] == "100"
