import { useCallback, useEffect, useState } from "react";
import api from "@/api";

/**
 * - loading:    haven't heard from the server yet
 * - connected:  launched from a course and holding a usable Canvas token
 * - expired:    launched from a course, but the token is gone (session timed out)
 * - no-course:  has a token, but we couldn't tell which course it was launched from
 * - standalone: not launched from Canvas
 */
export type CanvasState = "loading" | "connected" | "expired" | "no-course" | "standalone";

interface SessionResponse {
  canvas: { connected: boolean; course_id: string | null };
}

/**
 * The Canvas connection as the *server* sees it (GET /api/session). The UI used to guess
 * from a course id baked into the page and cached in sessionStorage, which kept saying
 * "Connected" long after the server-side token had expired.
 */
export function useCanvasSession() {
  const [loaded, setLoaded] = useState(false);
  const [connected, setConnected] = useState(false);
  const [courseId, setCourseId] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const { data } = await api.get<SessionResponse>("/session");
      setConnected(Boolean(data.canvas.connected));
      setCourseId(data.canvas.course_id ?? null);
    } catch {
      // If we can't ask, behave as standalone rather than claim a connection we can't confirm.
      setConnected(false);
      setCourseId(null);
    } finally {
      setLoaded(true);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  let state: CanvasState;
  if (!loaded) state = "loading";
  else if (connected && courseId) state = "connected";
  else if (courseId) state = "expired";
  else if (connected) state = "no-course";
  else state = "standalone";

  return { state, courseId, refresh };
}
