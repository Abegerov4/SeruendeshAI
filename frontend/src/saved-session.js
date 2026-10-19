// Saved-list ownership is shared by auth transitions and the application view.
export function createSavedSession(api) {
  let userId = null, places = [], generation = 0, pendingEdits = null;
  const listeners = new Set();
  const publish = next => { places = next; listeners.forEach(fn => fn()); };
  return {
    getSnapshot: () => places,
    subscribe: fn => { listeners.add(fn); return () => listeners.delete(fn); },
    async setUser(nextUserId) {
      if (nextUserId === userId) return;
      // Only cards selected as a guest may migrate into a newly opened account.
      const guest = userId === null && nextUserId !== null ? places : [];
      userId = nextUserId;
      const version = ++generation;
      pendingEdits = null;
      publish(guest);
      if (!userId) return;
      const edits = new Map();
      pendingEdits = edits;
      try {
        const server = await api.fetchSaved();
        if (version !== generation) return;
        const merged = new Map(server.map(p => [p.id, p]));
        for (const p of guest) if (!merged.has(p.id) && !edits.has(p.id)) {
          merged.set(p.id, p);
          api.putSaved(p).catch(() => {});
        }
        for (const [id, p] of edits) {
          if (p) merged.set(id, p);
          else merged.delete(id);
        }
        publish([...merged.values()]);
      } catch {
        // Keep the current account's optimistic edits when its request fails.
      } finally {
        if (version === generation) pendingEdits = null;
      }
    },
    toggle(place) {
      const exists = places.some(p => p.id === place.id);
      pendingEdits?.set(place.id, exists ? null : place);
      if (userId) (exists ? api.deleteSaved(place.id) : api.putSaved(place)).catch(() => {});
      publish(exists ? places.filter(p => p.id !== place.id) : [...places, place]);
    },
  };
}
