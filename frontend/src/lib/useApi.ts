import { useEffect, useRef, useState } from 'react'

export interface AsyncState<T> {
  data: T | null
  loading: boolean
  error: string | null
}

/** Run an async loader and track its lifecycle.
 *
 * `deps` is stringified into the effect key so callers can pass the filter
 * object directly without memoising it - filters are rebuilt on every render,
 * so an identity comparison would refetch forever.
 *
 * The sequence guard drops responses from superseded requests: switching
 * filters quickly can land an older, slower response after a newer one, and
 * without this the screen would show data for a filter the user has left.
 */
export function useApi<T>(loader: () => Promise<T>, deps: unknown[]): AsyncState<T> {
  const [state, setState] = useState<AsyncState<T>>({
    data: null,
    loading: true,
    error: null,
  })
  const sequence = useRef(0)
  const key = JSON.stringify(deps)

  useEffect(() => {
    const current = ++sequence.current
    setState((previous) => ({ ...previous, loading: true, error: null }))

    loader()
      .then((data) => {
        if (current === sequence.current) setState({ data, loading: false, error: null })
      })
      .catch((error: Error) => {
        if (current === sequence.current) {
          setState({ data: null, loading: false, error: error.message })
        }
      })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key])

  return state
}
