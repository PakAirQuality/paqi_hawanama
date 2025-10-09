'use client'

import { useState, useEffect } from 'react'

/**
 * Custom hook for managing state that persists across browser sessions
 */
export function usePersistentState<T>(
  key: string, 
  defaultValue: T
): [T, (value: T) => void] {
  const [state, setState] = useState<T>(defaultValue)

  // Load persisted state on mount
  useEffect(() => {
    try {
      const persistedValue = localStorage.getItem(key)
      if (persistedValue !== null) {
        setState(JSON.parse(persistedValue))
      }
    } catch (error) {
      console.warn(`Failed to load persisted state for key "${key}":`, error)
    }
  }, [key])

  // Update state and persist to localStorage
  const setPersistentState = (value: T) => {
    setState(value)
    try {
      localStorage.setItem(key, JSON.stringify(value))
    } catch (error) {
      console.warn(`Failed to persist state for key "${key}":`, error)
    }
  }

  return [state, setPersistentState]
}