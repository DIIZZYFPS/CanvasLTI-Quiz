import { AxiosError, type AxiosResponse } from "axios";
import { describe, expect, it } from "vitest";
import { readApiError } from "@/lib/errors";

function failure(data: unknown, status = 400): AxiosError {
  const response = { data, status, statusText: "", headers: {}, config: {} } as AxiosResponse;
  return new AxiosError("Request failed with status code " + status, "ERR_BAD_REQUEST", undefined, undefined, response);
}

describe("readApiError", () => {
  it("shows the reason the API gave", async () => {
    expect(await readApiError(failure({ error: "Quiz title is required" }))).toBe("Quiz title is required");
  });

  it("reads the reason out of a blob body (the QTI download asks for blobs)", async () => {
    const body = new Blob([JSON.stringify({ error: "Question 2 has no correct answer" })], { type: "application/json" });
    expect(await readApiError(failure(body))).toBe("Question 2 has no correct answer");
  });

  it("falls back to axios' message when a blob isn't JSON", async () => {
    const message = await readApiError(failure(new Blob(["<html>Bad Gateway</html>"]), 502));
    expect(message).toBe("Request failed with status code 502");
  });

  it("falls back to axios' message when the body has no error field", async () => {
    expect(await readApiError(failure({ detail: "x" }, 500))).toBe("Request failed with status code 500");
  });

  it("ignores an error field that isn't text", async () => {
    expect(await readApiError(failure({ error: { nested: true } }, 500))).toBe("Request failed with status code 500");
  });

  it("explains a request that never reached the server", async () => {
    const offline = new AxiosError("Network Error", "ERR_NETWORK");
    expect(await readApiError(offline)).toMatch(/couldn't reach the server/i);
  });

  it("uses the message of an ordinary Error", async () => {
    expect(await readApiError(new Error("Canvas is taking longer than expected."))).toBe("Canvas is taking longer than expected.");
  });

  it("uses the caller's fallback for anything else", async () => {
    expect(await readApiError("boom", "Export failed.")).toBe("Export failed.");
    expect(await readApiError(undefined)).toBe("Something went wrong");
  });
});
