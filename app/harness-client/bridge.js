/* Injected by the checked client adapter inside ui-conversation's apply scope.
 * This delegates to the resident InputHub; it never reproduces prompt/stream protocols.
 */
function installFoundryEmbeddedBridge(ctx, sessions, inputHub, composerBlocks, page = window, doc = document) {
  const requests = new Map();
  const touched = new Set();
  let serial = Promise.resolve();
  let disposed = false;
  const delay = () => new Promise((resolve) => setTimeout(resolve, 25));
  async function waitFor(read, message) {
    const end = Date.now() + 12000;
    while (!disposed && Date.now() < end) {
      const value = read();
      if (value) return value;
      await delay();
    }
    throw new Error(message);
  }
  async function settleAdmission(shell, receipt, key, sessionId) {
    if (receipt.machineId !== shell.core.foundryId) return {sessionId, submitted: false, blockedReason: '上次提交结果尚未确认，请先查看对话记录；问题没有自动重发。'};
    const end = Date.now() + 30000;
    while (!disposed && Date.now() < end) {
      const admission = shell.core.foundryAdmission;
      if (admission?.seq === receipt.seq) {
        if (admission.ok) page.localStorage.setItem(key, JSON.stringify({...receipt, status: 'succeeded'}));
        else page.localStorage.removeItem(key);
        return {sessionId, submitted: Boolean(admission.ok), ...(!admission.ok ? {blockedReason: admission.message ?? '问题尚未发送，请检查设置后重试。'} : {})};
      }
      await delay();
    }
    return {sessionId, submitted: false, blockedReason: '提交仍在确认中，请稍后重试；重试会等待本次结果。'};
  }
  const api = {
    version: 1,
    async dispatch(request) {
      if (!request || typeof request.sessionId !== 'string' || !request.sessionId || request.sessionId.length > 200) throw new Error('invalid embedded session');
      if (request.draft !== undefined && (typeof request.draft !== 'string' || request.draft.length > 100000 || request.draft.includes('\0'))) throw new Error('invalid embedded draft');
      if (request.submit && (!request.requestId || typeof request.requestId !== 'string' || request.requestId.length > 200 || !request.draft?.trim())) throw new Error('submission needs question and action id');
      const fingerprint = JSON.stringify([request.sessionId, request.draft, Boolean(request.submit)]);
      const old = request.requestId && requests.get(request.requestId);
      if (old) {
        if (old.fingerprint !== fingerprint) throw new Error('action id was reused for different content');
        return old.result;
      }
      const result = serial.then(async () => {
        if (disposed) throw new Error('embedded conversation is unavailable');
        if (!sessions.list.getSnapshot().byId[request.sessionId]) await sessions.refresh();
        sessions.open(request.sessionId);
        const session = await waitFor(() => {
          const bound = sessions.binding(request.sessionId)?.session;
          return sessions.list.getSnapshot().current === request.sessionId && bound?.getSnapshot().openState === 'open' ? bound : undefined;
        }, '会话尚未连接，请稍后重试。');
        const shell = inputHub.shell(request.sessionId);
        // React binds the persisted draft mirror before a handoff writes into the machine.
        await waitFor(() => shell.mirrorFn, '输入框尚未就绪，请稍后重试。');
        touched.add(request.sessionId);
        const submittedKey = `fnd.submitted.${request.sessionId}.${request.requestId}`;
        let receipt;
        try { receipt = JSON.parse(page.localStorage.getItem(submittedKey) ?? 'null'); } catch {}
        if (request.submit && receipt) {
          if (receipt.fingerprint !== fingerprint) throw new Error('persisted action id content changed');
          if (receipt.status === 'succeeded') return {sessionId: request.sessionId, submitted: true};
          return await settleAdmission(shell, receipt, submittedKey, request.sessionId);
        }
        if (request.draft !== undefined) {
          if (['adjudicating', 'submitting'].includes(shell.snapshot.phase)) throw new Error('输入正在提交，请稍后重试。');
          const previous = shell.snapshot.draft;
          const draft = !request.submit && previous && previous !== request.draft
            ? `${previous}\n\n${request.draft}` : request.draft;
          shell.actions.setDraft(draft);
        }
        touched.add(request.sessionId);
        const snapshot = session.getSnapshot();
        const block = composerBlocks.storeFor(request.sessionId).getSnapshot();
        const input = doc.querySelector('[data-composer-card] textarea');
        let submitted = false;
        let blockedReason;
        if (request.submit) {
          if (snapshot.removed || snapshot.subagent || block || !input || input.disabled) {
            blockedReason = block?.reason ?? '请先在对话中完成模型设置，再发送已保留的问题。';
          } else {
            const receipt = {fingerprint, status: 'pending', machineId: shell.core.foundryId, seq: shell.core.seq + 1};
            page.localStorage.setItem(submittedKey, JSON.stringify(receipt));
            shell.actions.submit();
            const outcome = await settleAdmission(shell, receipt, submittedKey, request.sessionId);
            submitted = outcome.submitted;
            blockedReason = outcome.blockedReason;
          }
        }
        if (request.draft !== undefined) input?.focus({ preventScroll: true });
        return { sessionId: request.sessionId, submitted, ...(blockedReason ? { blockedReason } : {}) };
      });
      serial = result.catch(() => {});
      if (request.requestId) {
        requests.set(request.requestId, {fingerprint, result});
        result.then(reply => { if (!reply.submitted) requests.delete(request.requestId); }, () => requests.delete(request.requestId));
      }
      return result;
    },
    snapshot() {
      const drafts = {};
      for (const id of touched) {
        const key = `dsh.conversation.chat.${id}`;
        try { drafts[id] = JSON.parse(page.localStorage.getItem(key) ?? 'null'); } catch {}
      }
      const receipts = {};
      for (let i = 0; i < page.localStorage.length; i++) {
        const key = page.localStorage.key(i);
        if (key?.startsWith('fnd.submitted.')) receipts[key] = page.localStorage.getItem(key);
      }
      return {drafts, receipts};
    },
  };
  ctx.effect(() => {
    page.__foundryEmbedded = api;
    return () => { disposed = true; if (page.__foundryEmbedded === api) delete page.__foundryEmbedded; };
  }, 'foundry: embedded input handoff');
}
