"""Real CLI acceptance with synthetic data. Works against source or frozen CLI.

Run: python tools/verify_analysis_workbench.py --foundry .venv/bin/foundry
No model key, user documents or existing task state is used.
"""
from __future__ import annotations
import argparse
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile


def main():
    p=argparse.ArgumentParser();p.add_argument('--foundry', required=True);p.add_argument('--output')
    args=p.parse_args();binary=str(Path(args.foundry).resolve())
    with tempfile.TemporaryDirectory(prefix='foundry-acceptance-') as temp:
        root=Path(temp).resolve();var=root/'var'
        def call(command,*parts,task=None,raw=False):
            result=subprocess.run([binary,'--var',str(var),*(['--task',task] if task else []),command,*map(str,parts)],capture_output=True,text=True,timeout=90)
            if result.returncode: raise AssertionError(f'{command}: {result.stderr}')
            return result.stdout.strip() if raw else json.loads(result.stdout)
        def spec(command,value,task): return call(command,'--spec',json.dumps(value,ensure_ascii=False),task=task)
        def dataset(task,name,rows):
            path=root/(name+'.json');path.write_text(json.dumps(rows,ensure_ascii=False),encoding='utf8')
            return call('dataset-add','--path',path,'--name',name,'--meta',json.dumps({'currency':'CNY','unit':'万元'}),task=task)['id']
        def run(task,definition):
            analysis=spec('analysis-save',definition,task)
            result=call('analysis-run','--analysis',analysis['id'],task=task)
            assert result['execution_status']=='succeeded', result
            return analysis,result
        finance=call('task-new','--title','验收：经营利润与预算',raw=True)
        actual=dataset(finance,'实际',[{'region':'华东','revenue':120,'cost':70,'expense':20}])
        budget=dataset(finance,'预算',[{'region':'华东','revenue':100,'cost':60,'expense':15}])
        definition={'question':'华东利润对预算差异','bindings':{'actual':actual,'budget':budget},
            'relationships':[{'left':'actual','right':'budget','keys':['region'],'cardinality':'one-to-one'}],
            'sql':'SELECT a.revenue-a.cost-a.expense AS actual_profit,b.revenue-b.cost-b.expense AS budget_profit,(a.revenue-a.cost-a.expense)-(b.revenue-b.cost-b.expense) AS variance FROM actual a JOIN budget b USING(region)'}
        analysis,profit=run(finance,definition)
        assert {k:Decimal(v) for k,v in profit['result']['rows'][0].items()}=={'actual_profit':30,'budget_profit':25,'variance':5}
        bridge_def={**definition,'sql':"SELECT a.revenue-b.revenue AS revenue_effect,-(a.cost-b.cost) AS cost_effect,-(a.expense-b.expense) AS expense_effect,((a.revenue-a.cost-a.expense)-(b.revenue-b.cost-b.expense))/(b.revenue-b.cost-b.expense) AS variance_rate FROM actual a JOIN budget b USING(region)"}
        _,bridge=run(finance,bridge_def)
        assert {k:Decimal(v) for k,v in bridge['result']['rows'][0].items()}=={'revenue_effect':20,'cost_effect':-10,'expense_effect':-5,'variance_rate':Decimal('0.2')}
        history=dataset(finance,'上期与其他地区',[{'region':'华东','profit':20},{'region':'西南','profit':10}])
        _,comparison=run(finance,{'question':'华东利润环比，排除西南','bindings':{'actual':actual,'previous':history},'relationships':[{'left':'actual','right':'previous','keys':['region'],'cardinality':'one-to-one'}],
            'sql':"SELECT a.revenue-a.cost-a.expense-p.profit AS increase,(a.revenue-a.cost-a.expense-p.profit)/p.profit AS growth FROM actual a JOIN previous p USING(region) WHERE a.region=?",'parameters':['华东']})
        assert {k:Decimal(v) for k,v in comparison['result']['rows'][0].items()}=={'increase':10,'growth':Decimal('0.5')}
        _,partial=run(finance,{'question':'暂缺预算时继续分析实际','bindings':{'actual':actual},'sql':'SELECT revenue-cost-expense AS profit FROM actual','missing_inputs':['budget']})
        assert Decimal(partial['result']['rows'][0]['profit'])==30 and partial['missing_inputs']==['budget']
        replay=call('analysis-run','--analysis',analysis['id'],task=finance)
        assert replay['output_hash']==profit['output_hash'] and replay['reproducibility_status']=='reproducible'
        note=root/'背景.md';note.write_text('总部费用包含一次性招聘费用。\n\n管理口径可选择单列，但不等于调账。',encoding='utf8')
        background=call('dataset-add','--path',note,'--name','管理背景',task=finance)
        assert call('dataset-read','--dataset',background['id'],task=finance)['paragraphs']
        revised,adjusted=run(finance,{'question':'单列总部费用后的贡献利润','bindings':{'actual':actual},
            'sql':'SELECT revenue-cost-expense+CAST(? AS DECIMAL(38,2)) AS profit FROM actual','parameters':['5'],
            'assumptions':[{'name':'单列总部费用','value':'5','basis':'user_assumption'}],'parent_id':analysis['id']})
        assert Decimal(adjusted['result']['rows'][0]['profit'])==35
        draft=spec('analysis-draft',{'title':'经营简报','body':'华东实际利润30万元，预算25万元，超预算5万元。单列总部费用的测算需另行说明。',
            'run_ids':[replay['id']],'claims':[{'basis':'calculation','run_id':replay['id'],'row':0,'column':'variance','value':'5'}],
            'review_status':'accepted','publication_status':'archived'},finance)
        exported=call('analysis-export','--draft',draft['id'],'--format','md',task=finance)
        old=Path(exported['path']).read_bytes();assert hashlib.sha256(old).hexdigest()==exported['sha256']
        revision=spec('analysis-draft',{'parent_id':draft['id'],'body':'补充：管理层关注持续性利润，单列总部费用后的测算为35万元。','claims':[{'basis':'professional_judgment','text':'关注持续性利润'}]},finance)
        assert revision['publication_status']=='draft' and Path(exported['path']).read_bytes()==old
        workbook=call('analysis-export','--draft',revision['id'],'--format','xlsx',task=finance)
        assert Path(workbook['path']).read_bytes().startswith(b'PK')
        method=call('analysis-method-save','--analysis',revised['id'],'--name','单列费用测算',task=finance)
        reused=call('analysis-method-apply','--method',method['id'],'--bindings',json.dumps({'actual':actual}),'--parameters','["10"]',task=finance)
        assert Decimal(call('analysis-run','--analysis',reused['id'],task=finance)['result']['rows'][0]['profit'])==40
        cash=call('task-new','--title','验收：回款与现金预测',raw=True)
        other_actual=dataset(cash,'其他任务实际',[{'region':'华东','revenue':180,'cost':60,'expense':30}])
        new_method=call('analysis-method-apply','--method',method['id'],'--bindings',json.dumps({'actual':other_actual}),'--parameters','["10"]',task=cash)
        assert Decimal(call('analysis-run','--analysis',new_method['id'],task=cash)['result']['rows'][0]['profit'])==100
        receivables=dataset(cash,'应收',[{'customer':'甲','due':'2026-08-01','amount':80},{'customer':'乙','due':'2026-09-20','amount':20}])
        _,aging=run(cash,{'question':'优先跟进谁','bindings':{'ar':receivables},'sql':'SELECT customer,amount,DATE_DIFF(\'day\',CAST(due AS DATE),CAST(? AS DATE)) AS overdue_days FROM ar WHERE CAST(due AS DATE)<CAST(? AS DATE) ORDER BY amount DESC','parameters':['2026-09-05','2026-09-05']})
        assert aging['result']['rows'][0]['customer']=='甲' and Decimal(aging['result']['rows'][0]['overdue_days'])==35
        schedule=dataset(cash,'回款计划',[{'due':'2026-09-25','inflow':100,'outflow':60}])
        forecast={'question':'回款晚两周，季度现金余额如何变化','bindings':{'plan':schedule},'sql':"SELECT CAST(? AS DECIMAL(38,2))+SUM(CASE WHEN CAST(due AS DATE)+CAST(? AS INTEGER)<=CAST(? AS DATE) THEN inflow ELSE 0 END)-SUM(outflow) AS ending_cash FROM plan",'parameters':['50',0,'2026-09-30']}
        first,base=run(cash,forecast);forecast.update(parameters=['50',14,'2026-09-30'],parent_id=first['id'],assumptions=[{'name':'回款延迟天数','value':14}])
        _,delayed=run(cash,forecast)
        assert Decimal(base['result']['rows'][0]['ending_cash'])==90 and Decimal(delayed['result']['rows'][0]['ending_cash'])==-10
        assert call('analysis-state',task=finance)['task_id']==finance
        result={'status':'passed','cases':['budget_variance','variance_bridge','previous_period','missing_budget','cross_task_method','repeat_hash','background_document','assumption_revision','draft_archive_revision','xlsx_export','method_reuse','receivables_aging','cash_delay_scenario','task_switch'],
                'budget_variance':'5','base_cash':'90','delayed_cash':'-10','draft_sha256':exported['sha256'],'workbook_sha256':workbook['sha256']}
        if args.output: Path(args.output).write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
        print(json.dumps(result,ensure_ascii=False))

if __name__=='__main__':main()
