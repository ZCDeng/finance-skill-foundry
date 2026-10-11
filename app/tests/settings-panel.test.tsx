// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, expect, it } from 'vitest';
import { SettingsGroup, SettingsPanel, useSettingsPanel } from '../src/views/analysis/SettingsPanel.js';

afterEach(cleanup);

function Harness({ initialOpen = false }: { initialOpen?: boolean }) {
  const settings = useSettingsPanel(initialOpen);
  return <SettingsGroup note="分区说明">
    <SettingsPanel state={settings} label="范围与计算" summary="入口说明"><input aria-label="期间" /></SettingsPanel>
  </SettingsGroup>;
}

const summary = () => document.querySelector<HTMLElement>('details.analysis-finance-setup > summary')!;
/** A click on the summary, as the browser delivers it: the native toggle, then React's onToggle. */
function toggle(open: boolean) {
  const details = summary().parentElement as HTMLDetailsElement;
  details.open = open;
  fireEvent(details, new Event('toggle'));
}

it('draws one section heading with its note below and the fold under it', () => {
  render(<Harness />);
  const heading = screen.getByRole('heading', { name: '自己动手算', level: 3 });
  expect(heading.nextElementSibling?.textContent).toBe('分区说明');
  expect(summary().textContent).toBe('范围与计算 · 入口说明');
  expect(screen.queryByRole('region', { name: '范围与计算' })).toBeNull();
});

it('opens in place from its line, keeps focus there, and hands it back on Escape', () => {
  render(<Harness />);
  summary().focus();
  toggle(true);
  expect(screen.getByRole('region', { name: '范围与计算' })).toBeTruthy();
  expect(document.activeElement).toBe(summary());
  fireEvent.keyDown(screen.getByLabelText('期间'), { key: 'Escape' });
  expect(screen.queryByRole('region', { name: '范围与计算' })).toBeNull();
  expect(document.activeElement).toBe(summary());
});

it('can start open without stealing focus', () => {
  render(<Harness initialOpen />);
  expect(screen.getByRole('region', { name: '范围与计算' })).toBeTruthy();
  expect(document.activeElement).toBe(document.body);
});

function AskHarness() {
  const settings = useSettingsPanel();
  return <><button type="button" onClick={settings.openWithFocus}>调整范围</button>
    <SettingsPanel state={settings} label="范围与计算"><button type="button" onClick={settings.close}>计算</button></SettingsPanel></>;
}

it('moves focus in when another control asks for it, and back to that control on close', () => {
  render(<AskHarness />);
  const asker = screen.getByRole('button', { name: '调整范围' });
  asker.focus();
  fireEvent.click(asker);
  const region = screen.getByRole('region', { name: '范围与计算' });
  expect(document.activeElement).toBe(region);
  fireEvent.click(screen.getByRole('button', { name: '计算' }));
  expect(document.activeElement).toBe(asker);
});

function RunHarness() {
  const settings = useSettingsPanel();
  return <SettingsPanel state={settings} label="范围与计算">
    <button type="button" onClick={() => settings.setOpen(false)}>计算</button>
  </SettingsPanel>;
}

it('hands focus back to its line when a run closes the fold a person opened', () => {
  render(<RunHarness />);
  summary().focus();
  toggle(true);
  const run = screen.getByRole('button', { name: '计算' });
  run.focus();
  fireEvent.click(run);
  expect(screen.queryByRole('region', { name: '范围与计算' })).toBeNull();
  expect(document.activeElement).toBe(summary());
});
