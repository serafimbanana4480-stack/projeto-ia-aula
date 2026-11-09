"use client";

/** Geometric identity derived from the agent name. Color comes from the same
 *  agent palette the transcript already uses; the shape is not a status. */
export default function IdentityMark({ name, color }: { name: string; color: string }) {
  let hash = 0;
  for (const char of name || "NEXUS") hash = (hash * 33 + char.charCodeAt(0)) >>> 0;
  const cx = 9 + (hash % 5);
  const r = 3.5 + ((hash >> 3) % 3);
  const tilt = (hash >> 6) % 2 === 0 ? 12 : -16;

  return (
    <svg width="36" height="36" viewBox="0 0 36 36" aria-hidden="true" className="shrink-0">
      <rect width="36" height="36" rx="12" fill={color} fillOpacity="0.14" />
      <circle cx={cx} cy="13" r={r} fill={color} />
      <rect
        x="16"
        y="15"
        width="11"
        height="11"
        rx="3"
        fill={color}
        fillOpacity="0.72"
        transform={`rotate(${tilt} 21.5 20.5)`}
      />
      <path
        d={`M7 28 C14 ${18 + (hash % 6)}, 22 30, 30 22`}
        stroke={color}
        strokeWidth="1.4"
        fill="none"
      />
    </svg>
  );
}
