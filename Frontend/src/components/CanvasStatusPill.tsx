import { AlertCircle } from "lucide-react";
import type { CanvasState } from "@/hooks/useCanvasSession";

interface CanvasStatusPillProps {
  state: CanvasState;
  courseId: string | null;
}

const BASE = "flex items-center gap-2 whitespace-nowrap rounded-full border px-3 py-1.5 text-xs";

/** Header badge showing the Canvas connection as the server sees it. */
export function CanvasStatusPill({ state, courseId }: CanvasStatusPillProps) {
  switch (state) {
    case "loading":
      // Same footprint as the real pill so the header doesn't jump when the answer arrives.
      return <div className="h-8 w-44 animate-pulse rounded-full bg-muted motion-reduce:animate-none" aria-hidden="true" />;

    case "connected":
      return (
        <div className={`${BASE} border-success/30 bg-success/10 font-semibold text-success shadow-sm`}>
          <span className="relative flex h-2 w-2" aria-hidden="true">
            <span className="animate-ping motion-reduce:animate-none absolute inline-flex h-full w-full rounded-full bg-success opacity-60"></span>
            <span className="relative inline-flex rounded-full h-2 w-2 bg-success"></span>
          </span>
          <span>Canvas Connected</span>
          <span className="w-1 h-1 rounded-full bg-success/40" aria-hidden="true" />
          <span className="font-mono">
            <span className="hidden sm:inline">Course ID: </span>
            {courseId}
          </span>
        </div>
      );

    case "expired":
      return (
        <div
          className={`${BASE} border-warning/30 bg-warning/10 font-medium text-warning`}
          title="Relaunch the tool from your Canvas course to upload directly."
        >
          <AlertCircle className="h-3.5 w-3.5" aria-hidden="true" />
          Canvas session expired
        </div>
      );

    case "no-course":
      return (
        <div
          className={`${BASE} border-warning/30 bg-warning/10 font-medium text-warning`}
          title="Relaunch the tool from the course you want to upload to."
        >
          <AlertCircle className="h-3.5 w-3.5" aria-hidden="true" />
          Canvas course not detected
        </div>
      );

    case "standalone":
    default:
      // Not an error: using the tool outside Canvas is a normal mode, so no warning colours.
      return <div className={`${BASE} border-border bg-muted font-medium text-foreground`}>Standalone Mode</div>;
  }
}
