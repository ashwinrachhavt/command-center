export type RequestIntent = {
  signature: string;
  key: string;
};

export function requestSignature(
  method: string,
  target: string,
  body?: unknown,
) {
  return JSON.stringify({ method, target, body: body ?? null });
}

export class RetainedRequestIntent {
  private current?: RequestIntent;

  forSignature(signature: string): RequestIntent {
    if (this.current?.signature !== signature) {
      this.current = { signature, key: crypto.randomUUID() };
    }
    return this.current;
  }

  forRequest(method: string, target: string, body?: unknown) {
    return this.forSignature(requestSignature(method, target, body));
  }

  confirm(signature: string) {
    if (this.current?.signature === signature) this.current = undefined;
  }

  confirmRequest(method: string, target: string, body?: unknown) {
    this.confirm(requestSignature(method, target, body));
  }

  reset() {
    this.current = undefined;
  }
}

export class RetainedRequestIntents {
  private readonly slots = new Map<string, RetainedRequestIntent>();

  forRequest(slot: string, method: string, target: string, body?: unknown) {
    return this.slot(slot).forRequest(method, target, body);
  }

  confirmRequest(slot: string, method: string, target: string, body?: unknown) {
    this.slot(slot).confirmRequest(method, target, body);
  }

  reset(slot: string) {
    this.slots.delete(slot);
  }

  private slot(name: string) {
    let intent = this.slots.get(name);
    if (!intent) {
      intent = new RetainedRequestIntent();
      this.slots.set(name, intent);
    }
    return intent;
  }
}

export function canStartFreshConnectedRequest(error: unknown) {
  if (!error || typeof error !== "object" || !("code" in error)) return false;
  const code = error.code;
  return (
    code === "connected_request_failed" ||
    (typeof code === "string" && code.startsWith("spending_"))
  );
}
