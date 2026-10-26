export type TryonEngine = "standard" | "premium";
export type TryonStatus = "pending" | "processing" | "completed" | "failed";

export type TryonJob = {
  id: string;
  status: TryonStatus;
  engine: TryonEngine;
  error: string | null;
};

export class ClotheApiError extends Error {
  statusCode?: number;

  constructor(message: string, statusCode?: number) {
    super(message);
    this.statusCode = statusCode;
  }
}

async function readError(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as { detail?: string };
    return body.detail || `HTTP ${response.status}`;
  } catch {
    return `HTTP ${response.status}`;
  }
}

export class ClotheClient {
  constructor(
    private readonly storeId: string,
    private readonly storeName: string,
    private readonly apiKey: string,
    private readonly baseUrl = "http://127.0.0.1:8090",
  ) {}

  private url(path: string): string {
    const query = new URLSearchParams({ store_id: this.storeId, store_name: this.storeName });
    return `${this.baseUrl.replace(/\/$/, "")}${path}?${query}`;
  }

  private async request(path: string, init: RequestInit = {}): Promise<Response> {
    const headers = new Headers(init.headers);
    headers.set("Authorization", `Bearer ${this.apiKey}`);
    const response = await fetch(this.url(path), { ...init, headers });
    if (!response.ok) {
      throw new ClotheApiError(await readError(response), response.status);
    }
    return response;
  }

  async createTryon(person: Blob, garment: Blob, engine: TryonEngine = "standard"): Promise<TryonJob> {
    const form = new FormData();
    form.set("person_image", person, "person.jpg");
    form.set("garment_image", garment, "garment.jpg");
    form.set("engine", engine);
    const response = await this.request("/v1/tryon", { method: "POST", body: form });
    return (await response.json()) as TryonJob;
  }

  async get(jobId: string): Promise<TryonJob> {
    const response = await this.request(`/v1/tryon/${jobId}`);
    return (await response.json()) as TryonJob;
  }

  async result(jobId: string): Promise<Blob> {
    const response = await this.request(`/v1/tryon/${jobId}/result`);
    return response.blob();
  }

  async tryon(
    person: Blob,
    garment: Blob,
    engine: TryonEngine = "standard",
    timeoutMs = 180_000,
  ): Promise<TryonJob> {
    const started = Date.now();
    let job = await this.createTryon(person, garment, engine);
    while (job.status === "pending" || job.status === "processing") {
      if (Date.now() - started > timeoutMs) {
        throw new ClotheApiError("試穿逾時");
      }
      await new Promise((resolve) => setTimeout(resolve, 2000));
      job = await this.get(job.id);
    }
    if (job.status === "failed") {
      throw new ClotheApiError(job.error || "試穿失敗");
    }
    return job;
  }
}
