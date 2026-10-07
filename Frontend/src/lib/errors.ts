import axios from "axios";

/**
 * A human-readable message for a failed request.
 *
 * The API reports problems as `{ error: "..." }`. Requests made with
 * `responseType: 'blob'` (the QTI download) deliver that JSON body as a Blob, so
 * it has to be read back out - otherwise users see "Request failed with status
 * code 400" instead of the actual reason.
 */
export async function readApiError(err: unknown, fallback = "Something went wrong"): Promise<string> {
  if (axios.isAxiosError(err)) {
    const data: unknown = err.response?.data;
    if (data instanceof Blob) {
      try {
        const parsed = JSON.parse(await data.text());
        if (typeof parsed?.error === "string") return parsed.error;
      } catch {
        /* not JSON: fall through */
      }
    } else if (data && typeof data === "object" && typeof (data as { error?: unknown }).error === "string") {
      return (data as { error: string }).error;
    }
    if (!err.response) return "Couldn't reach the server. Check your connection and try again.";
    return err.message || fallback;
  }
  if (err instanceof Error) return err.message;
  return fallback;
}
