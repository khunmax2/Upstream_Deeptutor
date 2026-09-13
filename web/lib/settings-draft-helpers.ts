import type { Catalog } from "@/features/settings/store/SettingsStore";

/**
 * Fork. Put an embedding probe's detected dimension into the settings draft.
 *
 * Run test used to answer with the whole catalog it had just saved, and the
 * page replaced both its saved state and its draft with it: unsaved edits
 * elsewhere were lost, a profile that had only been typed in looked saved, and
 * its key came back masked (``***``) — which the next run then sent as the key.
 * The test now saves nothing but the dimension of an already-saved model, and
 * the page merges only that dimension into the one model it tested.
 */
export function withTestedEmbeddingDimension(
  draft: Catalog,
  profileId: string | null,
  modelId: string | null,
  dimension: number,
  supportedDimensions?: string,
): Catalog {
  const service = draft.services.embedding;
  if (!service || !profileId || !modelId || !(dimension > 0)) return draft;
  let changed = false;
  const profiles = service.profiles.map((profile) => {
    if (profile.id !== profileId) return profile;
    const models = profile.models.map((model) => {
      if (model.id !== modelId) return model;
      const nextDimension = String(dimension);
      const nextSupported = supportedDimensions ?? model.supported_dimensions;
      if (
        model.dimension === nextDimension &&
        model.supported_dimensions === nextSupported
      ) {
        return model;
      }
      changed = true;
      return {
        ...model,
        dimension: nextDimension,
        ...(nextSupported !== undefined
          ? { supported_dimensions: nextSupported }
          : {}),
      };
    });
    return changed ? { ...profile, models } : profile;
  });
  if (!changed) return draft;
  return {
    ...draft,
    services: { ...draft.services, embedding: { ...service, profiles } },
  };
}

/** The server's ``detail`` for a refused settings request, else its status. */
export async function settingsErrorDetail(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as { detail?: unknown } | null;
    if (body && typeof body.detail === "string" && body.detail) {
      return body.detail;
    }
  } catch {
    // Not JSON — fall through to the status line.
  }
  return `HTTP ${response.status}`;
}
