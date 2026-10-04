// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, expect, it } from 'vitest';
import { SettingsPanel, useSettingsPanel } from '../src/views/analysis/SettingsPanel.js';

afterEach(cleanup);

function Harness({ initialOpen = false }: { initialOpen?: boolean }) {
  const settings = useSettingsPanel(initialOpen);
  return <SettingsPanel state={settings} summary="入口说明" note="打开后的说明"><input aria-label="期间" /></SettingsPanel>;
}

it('opens in place from its entry, takes focus, and hands it back on Escape', () => {
  render(<Harness />);
  const entry = screen.getByRole('button', { name: '打开设置与高级' });
  expect(entry.getAttribute('aria-expanded')).toBe('false');
  expect(screen.queryByRole('dialog', { name: '设置与高级' })).toBeNull();
  entry.focus();
  fireEvent.click(entry);
  const panel = screen.getByRole('dialog', { name: '设置与高级' });
  expect(panel.getAttribute('aria-modal')).toBe('false');
  expect(document.activeElement).toBe(panel);
  expect(screen.queryByRole('button', { name: '打开设置与高级' })).toBeNull();
  fireEvent.keyDown(screen.getByLabelText('期间'), { key: 'Escape' });
  expect(screen.queryByRole('dialog', { name: '设置与高级' })).toBeNull();
  expect(document.activeElement).toBe(screen.getByRole('button', { name: '打开设置与高级' }));
});

it('can start open without stealing focus', () => {
  render(<Harness initialOpen />);
  expect(screen.getByRole('dialog', { name: '设置与高级' })).toBeTruthy();
  expect(document.activeElement).toBe(document.body);
  fireEvent.click(screen.getByRole('button', { name: '关闭设置与高级' }));
  expect(screen.getByRole('button', { name: '打开设置与高级' })).toBeTruthy();
});
