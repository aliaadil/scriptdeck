import { Card, CardContent } from "@/components/ui/card";

type Props = {
  onPick: (language: "python" | "node" | "bash") => void;
};

const CARDS = [
  { lang: "python" as const, emoji: "🐍", label: "Python", seed: "main.py + .env" },
  { lang: "node" as const, emoji: "🟢", label: "Node.js", seed: "main.js + .env" },
  { lang: "bash" as const, emoji: "➜", label: "Bash", seed: "main.sh + .env" },
];

export function QuickStartCards({ onPick }: Props) {
  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-3" data-testid="quick-start-cards">
      {CARDS.map((c) => (
        <Card
          key={c.lang}
          className="cursor-pointer transition-colors hover:border-primary"
          onClick={() => onPick(c.lang)}
          data-testid={`card-${c.lang}`}
        >
          <CardContent className="flex flex-col items-center gap-2 p-6 text-center">
            <span className="text-4xl" aria-hidden>{c.emoji}</span>
            <span className="font-semibold">{c.label}</span>
            <span className="text-xs text-muted-foreground">{c.seed}</span>
          </CardContent>
        </Card>
      ))}
    </div>
  );
}