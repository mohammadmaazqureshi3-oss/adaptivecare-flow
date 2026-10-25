const TEXT: Record<string, string> = {
  draft: "Draft",
  verified: "Verified",
  published: "Published",
  deployed: "Deployed",
  SAFE: "SAFE",
  UNSAFE: "UNSAFE",
  TOO_LARGE: "Too large",
};

export function StatusBadge({ status }: { status: string }) {
  return <span className={`badge badge-${status.toLowerCase()}`}>{TEXT[status] ?? status}</span>;
}
