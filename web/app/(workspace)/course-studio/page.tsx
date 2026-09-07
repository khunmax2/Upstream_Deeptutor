import MaicWorkspace from "@/components/maic/MaicWorkspace";
import { resolveOpenMaicEmbed } from "@/lib/openmaic-embed";

/**
 * Never prerendered, and a server component rather than a client one.
 *
 * The embed target is read from the environment and from
 * `data/user/settings/integrations.json` at request time. That keeps the URL
 * out of the client bundle (no NEXT_PUBLIC_ variable to bake in) and lets an
 * operator change it by editing the settings file.
 *
 * `force-dynamic` is what makes that true. The page calls no dynamic API of its
 * own, so without it `next build` would render it once and freeze whatever the
 * embed URL was *at build time* — which inside a Docker image is
 * "unconfigured", permanently.
 */
export const dynamic = "force-dynamic";

export default function MaicPage() {
  const { url, sameOrigin } = resolveOpenMaicEmbed();
  return <MaicWorkspace url={url} sameOrigin={sameOrigin} />;
}
