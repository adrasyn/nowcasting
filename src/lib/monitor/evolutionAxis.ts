import { finite } from "../monitor";

const niceStep = (minimum: number) => {
  const power = 10 ** Math.floor(Math.log10(minimum));
  return [1, 2, 2.5, 5, 10].map((n) => n * power)
    .find((step) => step >= minimum) ?? 10 * power;
};
const clean = (n: number) => Number(n.toPrecision(14)) || 0;

// Only the evolution chart uses this axis. Keep its zero baseline, contain
// every estimate/band edge, and allow at least 26 CSS pixels between ticks.
export function evolutionAxis(values: number[], height: number) {
  const valid = values.filter(finite);
  let low = Math.min(0, ...valid), high = Math.max(0, ...valid);
  if (!valid.length) { low = -1; high = 1; }
  else if (low === high) { low = -0.1; high = 0.1; }
  const available = finite(height) && height > 0 ? height : 137;
  const maximumTicks = Math.max(3, Math.min(6, Math.floor(available / 26) + 1));
  let step = niceStep((high - low) / (maximumTicks - 1));
  for (let attempt = 0; attempt < 20; attempt++) {
    if (!finite(step) || step <= 0) break;
    const first = Math.floor(low / step), last = Math.ceil(high / step);
    if (!finite(first) || !finite(last) || last - first > 100) break;
    const ticks = Array.from({ length: last - first + 1 }, (_, i) => clean((first + i) * step));
    if (ticks.length <= maximumTicks && ticks[0] <= low && ticks.at(-1)! >= high)
      return { min: ticks[0], max: ticks.at(-1)!, step, ticks };
    step = niceStep(step * 1.000001);
  }
  // Keep exceptional floating-point input bounded; never stall rendering.
  const bound = Math.max(1, ...valid.map(Math.abs));
  return { min: -bound, max: bound, step: bound, ticks: [-bound, 0, bound] };
}

export function evolutionTick(value: number, step: number) {
  let decimals = 0;
  while (decimals < 8 && Math.abs(Number(step.toFixed(decimals)) - step) > step * 1e-8)
    decimals++;
  if (decimals > 3 || Math.abs(value) >= 100000)
    return value === 0 ? "0" : value.toExponential(2).replace(/\.?0+e/, "e").replace("e+", "e");
  const label = value.toFixed(decimals);
  return decimals === 3 ? label.replace(/^(-?)0\./, "$1.") : label;
}
