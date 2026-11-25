"use client";

import clsx from "clsx";
import { FileUp } from "lucide-react";
import { useRef, useState } from "react";
import { api, ApiError } from "@/lib/api";
import type { Resume } from "@/lib/types";
import { Input, Spinner } from "./ui";

export function ResumeUpload({ onDone, defaultLabel = "My resume" }: { onDone: (r: Resume) => void; defaultLabel?: string }) {
  const [label, setLabel] = useState(defaultLabel);
  const [drag, setDrag] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const input = useRef<HTMLInputElement>(null);

  async function upload(file: File) {
    setError(null);
    if (file.type && file.type !== "application/pdf") {
      setError("Please choose a PDF.");
      return;
    }
    setBusy(true);
    const form = new FormData();
    form.append("file", file);
    form.append("label", label || "My resume");
    try {
      onDone(await api.upload<Resume>("/resumes", form));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Upload failed. Try again.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="grid gap-4">
      <label className="grid gap-2">
        <span className="label text-ink-2">Name this resume</span>
        <Input value={label} onChange={(e) => setLabel(e.target.value)} placeholder="e.g. SWE resume, ML resume" maxLength={120} />
      </label>
      <button
        type="button"
        onClick={() => input.current?.click()}
        onDragOver={(e) => {
          e.preventDefault();
          setDrag(true);
        }}
        onDragLeave={() => setDrag(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDrag(false);
          const f = e.dataTransfer.files[0];
          if (f) upload(f);
        }}
        disabled={busy}
        className={clsx(
          "grid min-h-44 place-items-center gap-3 rounded-md border-2 border-dashed px-6 py-10 text-center transition-colors",
          drag ? "border-amber bg-amber/10" : "border-rule-strong hover:border-ink-3 hover:bg-panel-2",
        )}
      >
        {busy ? (
          <span className="grid justify-items-center gap-3 text-ink-2">
            <Spinner className="size-6" />
            Reading your resume…
          </span>
        ) : (
          <span className="grid justify-items-center gap-2">
            <FileUp className="size-7 text-ink-2" />
            <span className="font-semibold text-ink">Drop your resume PDF here, or click to choose</span>
            <span className="text-sm text-ink-3">PDF up to 5 MB. We keep the parsed skills, not the file, and strip your contact details.</span>
          </span>
        )}
      </button>
      <input
        ref={input}
        type="file"
        accept="application/pdf"
        className="sr-only"
        onChange={(e) => {
          const f = e.target.files?.[0];
          if (f) upload(f);
          e.target.value = "";
        }}
      />
      {error && (
        <p role="alert" className="text-sm text-red">
          {error}
        </p>
      )}
    </div>
  );
}
