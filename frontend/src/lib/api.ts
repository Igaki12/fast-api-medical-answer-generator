export class ApiError extends Error {
  status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    ...init,
    headers: {
      ...(init?.headers ?? {})
    }
  });

  if (!res.ok) {
    let detailText = "";
    try {
      const data = await res.json();
      const detail = (data as { detail?: unknown }).detail;
      if (Array.isArray(detail)) {
        detailText = detail
          .map((item) => {
            const loc = Array.isArray(item?.loc) ? item.loc[item.loc.length - 1] : "error";
            const msg = typeof item?.msg === "string" ? item.msg : "invalid";
            return `${loc}: ${msg}`;
          })
          .join(" / ");
      } else if (typeof detail === "string") {
        detailText = detail;
      }
    } catch {
      detailText = await res.text().catch(() => "");
    }
    const message = `API Error: ${res.status} ${res.statusText}${
      detailText ? ` - ${detailText}` : ""
    }`.trim();
    throw new ApiError(message, res.status);
  }

  return (await res.json()) as T;
}

export type StartLegacyPipelineParams = {
  apiKey?: string;
  file: File;
  explanationName: string;
  university: string;
  year: string;
  subject: string;
  author: string;
};

export async function startLegacyPipeline(params: StartLegacyPipelineParams) {
  const fd = new FormData();
  if (params.apiKey) fd.append("api_key", params.apiKey);
  fd.append("input_file", params.file);
  fd.append("explanation_name", params.explanationName);
  fd.append("university", params.university);
  fd.append("year", params.year);
  fd.append("subject", params.subject);
  fd.append("author", params.author);

  return apiFetch<{ job_id: string; status?: string; message?: string }>("/api/v1/pipeline", {
    method: "POST",
    body: fd
  });
}

export async function getJobStatus(jobId: string, signal?: AbortSignal) {
  return apiFetch<{ status: string; message?: string; error?: string }>(
    `/api/v1/pipeline/${encodeURIComponent(jobId)}`,
    { signal }
  );
}

export async function downloadResult(jobId: string) {
  const res = await fetch(`/api/v1/pipeline/${encodeURIComponent(jobId)}/download`);
  if (!res.ok) {
    throw new ApiError(`Download failed: ${res.status} ${res.statusText}`, res.status);
  }

  const blob = await res.blob();
  const url = URL.createObjectURL(blob);

  const contentDisposition = res.headers.get("content-disposition") ?? "";
  const match = contentDisposition.match(/filename\*=UTF-8''([^;]+)|filename="?([^;]+)"?/i);
  let filename = decodeURIComponent(match?.[1] || match?.[2] || `${jobId}.pdf`);
  filename = filename.trim().replace(/,pdf_$/i, ".pdf");
  if (!filename.toLowerCase().endsWith(".pdf")) {
    filename = `${filename}.pdf`;
  }

  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();

  URL.revokeObjectURL(url);
}
