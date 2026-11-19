// Sort the calendar day actually displayed, never the observation period.
export function storedDay(value) {
  if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}(?:$|T)/.test(value))
    return null;
  const day = value.slice(0, 10),
    parsed = new Date(day + "T00:00:00Z");
  if (
    !Number.isFinite(parsed.getTime()) ||
    parsed.toISOString().slice(0, 10) !== day
  )
    return null;
  if (value.length > 10 && !Number.isFinite(Date.parse(value))) return null;
  return day;
}
export function displayUpdateInfo(indicator) {
  const checked = storedDay(indicator.source_checked_at);
  if (checked) return { day: checked, kind: "checked", label: "Checked" };
  const updated = storedDay(indicator.last_release_date);
  return updated
    ? { day: updated, kind: "updated", label: "Updated" }
    : { day: null, kind: null, label: null };
}
const lexical = (a, b) => (a < b ? -1 : a > b ? 1 : 0);
export function compareDisplayedUpdates(a, b) {
  const ad = displayUpdateInfo(a).day,
    bd = displayUpdateInfo(b).day;
  if (ad !== bd) {
    if (ad === null) return 1;
    if (bd === null) return -1;
    return lexical(bd, ad);
  }
  return (
    String(a.name || "").localeCompare(String(b.name || ""), "en-AU", {
      sensitivity: "base",
    }) || lexical(String(a.id), String(b.id))
  );
}
