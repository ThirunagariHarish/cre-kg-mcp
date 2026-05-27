import '@testing-library/jest-dom'

// Zustand's persist middleware calls localStorage.setItem / getItem.
// jsdom needs a URL origin to make localStorage available; without one the
// storage object exists but its methods are no-ops.  Provide a simple
// in-memory replacement so the persist middleware works in all test files.
const _store: Record<string, string> = {}

const localStorageMock: Storage = {
  getItem: (key: string) => _store[key] ?? null,
  setItem: (key: string, value: string) => { _store[key] = value },
  removeItem: (key: string) => { delete _store[key] },
  clear: () => { Object.keys(_store).forEach(k => delete _store[k]) },
  key: (index: number) => Object.keys(_store)[index] ?? null,
  get length() { return Object.keys(_store).length },
}

Object.defineProperty(globalThis, 'localStorage', {
  value: localStorageMock,
  writable: true,
})
