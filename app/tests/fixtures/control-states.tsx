import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { MessageSquare } from 'lucide-react';

import '../../src/styles/base.css';
import '../../src/components/components.css';
import '../../src/views/analysis.css';
import '../../src/components/workspace.css';
import { Button } from '../../src/components/ui/button.js';
import { Input } from '../../src/components/ui/input.js';
import { Textarea } from '../../src/components/ui/textarea.js';
import { Tabs, TabsList, TabsTrigger } from '../../src/components/ui/tabs.js';
import { AccountingPeriodInput, DateInput, DecimalInput, TextField } from '../../src/components/FinancialControls.js';

function ControlStatesFixture() {
  return (
    <StrictMode>
      <main className="analysis-workspace" style={{ padding: 24, maxWidth: 760 }}>
        <section aria-label="fields" className="analysis-edit-grid">
          <TextField label="账簿" value="" placeholder="ledger" onChange={() => {}} />
          <TextField label="账簿错误" value="bad" error="错误" onChange={() => {}} />
          <TextField label="账簿禁用" value="disabled" disabled onChange={() => {}} />
          <label>
            Shadcn Input
            <Input aria-label="shadcn input" placeholder="input" />
          </label>
          <label>
            Shadcn Input Error
            <Input aria-label="shadcn input error" aria-invalid="true" defaultValue="bad" />
          </label>
          <label>
            Shadcn Input Disabled
            <Input aria-label="shadcn input disabled" disabled defaultValue="disabled" />
          </label>
          <label>
            Shadcn Textarea
            <Textarea aria-label="shadcn textarea" placeholder="textarea" />
          </label>
          <label>
            Shadcn Textarea Error
            <Textarea aria-label="shadcn textarea error" aria-invalid="true" defaultValue="bad" />
          </label>
          <label>
            Shadcn Textarea Disabled
            <Textarea aria-label="shadcn textarea disabled" disabled defaultValue="disabled" />
          </label>
          <AccountingPeriodInput label="期间" value="" onChange={() => {}} />
          <DateInput label="日期" value="" onChange={() => {}} />
          <DecimalInput label="金额" value="" onChange={() => {}} unit="CNY" />
        </section>
        <section aria-label="actions" className="analysis-actions">
          <Button variant="ghost" type="button" aria-label="ghost action">
            <MessageSquare size={14} aria-hidden />讨论
          </Button>
          <Button variant="link" type="button" aria-label="link action">
            链接动作
          </Button>
          <Button type="button" aria-label="primary action">主要动作</Button>
          <Button variant="ghost" type="button" aria-label="disabled ghost action" disabled>禁用</Button>
          <Tabs defaultValue="data">
            <TabsList aria-label="fixture tabs">
              <TabsTrigger value="data">资料 <span>0</span></TabsTrigger>
              <TabsTrigger value="drafts">文稿 <span>1</span></TabsTrigger>
            </TabsList>
          </Tabs>
        </section>
      </main>
    </StrictMode>
  );
}

const root = document.getElementById('root');
if (!root) throw new Error('missing root');
createRoot(root).render(<ControlStatesFixture />);
