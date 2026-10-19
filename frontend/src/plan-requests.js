// Only the current search may publish a result or its resolved origin.
export function createPlanRequests() {
  let generation = 0, activeController = null;
  return {
    invalidate() { generation += 1; activeController?.abort(); },
    async run({text, context, lang, signal, resolveContext, recommend, onContext, onPlan, onLoading}) {
      const version = ++generation;
      activeController?.abort();
      const controller = new AbortController();
      activeController = controller;
      const abort = () => controller.abort();
      if (signal?.aborted) abort();
      else signal?.addEventListener('abort', abort, {once: true});
      const checkCurrent = () => {
        if (version !== generation || controller.signal.aborted) throw new DOMException('Aborted', 'AbortError');
      };
      onLoading(true);
      try {
        checkCurrent();
        const resolved = await resolveContext(context);
        checkCurrent();
        const plan = await recommend(text, resolved, lang, {signal: controller.signal});
        checkCurrent();
        onContext(plan.context);
        onPlan(plan);
        return plan;
      } catch (error) {
        checkCurrent();
        throw error;
      } finally {
        signal?.removeEventListener('abort', abort);
        if (version === generation) onLoading(false);
      }
    },
  };
}
