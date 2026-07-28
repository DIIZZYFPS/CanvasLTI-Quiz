/// <reference types="vite/client" />

interface Window {
  // Injected server-side by app/utils/render_utils.py when an LTI launch
  // carries a Canvas course id.
  CANVAS_COURSE_ID?: string;
}
