interface BadgeProps {
  children: React.ReactNode;
  variant?: "default" | "green" | "yellow" | "red" | "gray" | "blue" | "purple";
  className?: string;
}

export function Badge({ children, variant = "default", className = "" }: BadgeProps) {
  const variants = {
    default: "bg-gray-100 text-gray-700",
    green: "bg-green-100 text-green-700",
    yellow: "bg-yellow-100 text-yellow-700",
    red: "bg-red-100 text-red-700",
    gray: "bg-gray-100 text-gray-500",
    blue: "bg-blue-100 text-blue-700",
    purple: "bg-purple-100 text-purple-700",
  };
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium ${variants[variant]} ${className}`}>
      {children}
    </span>
  );
}

export function ScoreBadge({ score }: { score?: number | null }) {
  if (score == null) return <Badge variant="gray">—</Badge>;
  if (score >= 70) return <Badge variant="green">{score}</Badge>;
  if (score >= 50) return <Badge variant="yellow">{score}</Badge>;
  return <Badge variant="red">{score}</Badge>;
}

export function StatusBadge({ status }: { status: string }) {
  const map: Record<string, "green" | "yellow" | "blue" | "purple" | "red" | "gray"> = {
    imported: "gray",
    scored: "blue",
    contacted: "yellow",
    replied: "purple",
    booked: "green",
    closed: "gray",
    not_interested: "red",
    bounced: "red",
    active: "green",
    paused: "yellow",
    draft: "gray",
  };
  return <Badge variant={map[status] ?? "default"}>{status.replace("_", " ")}</Badge>;
}

export function SentimentBadge({ sentiment }: { sentiment?: string | null }) {
  if (!sentiment) return null;
  const map: Record<string, "green" | "yellow" | "red"> = {
    positive: "green",
    neutral: "yellow",
    negative: "red",
  };
  return <Badge variant={map[sentiment] ?? "default"}>{sentiment}</Badge>;
}
