import Link from "next/link";
import { Wordmark } from "@/components/ui";

export const metadata = { title: "Privacy" };

const POINTS = [
  ["What we keep", "Your Google name, email and picture; the text of resumes you upload with emails and phone numbers removed; the skills and level we read from them; your preferences, tracker, alerts, assistant chats and the things you ask it to remember; which roles you save, hide or open."],
  ["What we don’t", "The resume file itself is read once and thrown away. We never post anywhere, apply on your behalf or contact employers."],
  ["Who sees it", "Only you. Resume text is sent to an AI provider (such as Groq or Google Gemini) only when you use AI features like the fit check or the assistant."],
  ["Your controls", "Download everything we hold, or delete your account and all of it, from Settings at any time."],
  ["Where jobs come from", "Public job boards that companies publish themselves, plus a few public job APIs. Every role links back to its original posting."],
];

export default function Privacy() {
  return (
    <main className="mx-auto max-w-3xl px-4 py-10 md:px-6">
      <Wordmark />
      <h1 className="score mt-12 text-[3.5rem] font-extrabold uppercase leading-[0.9]">Privacy, plainly.</h1>
      <dl className="ruled mt-10 border-y border-rule">
        {POINTS.map(([k, v]) => (
          <div key={k} className="grid gap-2 py-5 md:grid-cols-[12rem_1fr] md:gap-8">
            <dt className="font-semibold">{k}</dt>
            <dd className="leading-relaxed text-ink-2">{v}</dd>
          </div>
        ))}
      </dl>
      <p className="mt-8 text-sm text-ink-2">
        <Link href="/" className="underline">
          Back to Rolecall
        </Link>
      </p>
    </main>
  );
}
