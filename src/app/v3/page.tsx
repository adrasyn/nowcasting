// `/v3` is where this page lived while it was a preview. The homepage serves it
// now, and this route is kept so that links made during the preview — in the PR,
// in notes, in chat — still resolve rather than 404. One implementation, two
// URLs, so the two cannot drift.
export { default } from "../page";
