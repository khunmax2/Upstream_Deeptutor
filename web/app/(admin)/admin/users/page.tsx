import AdminUsersClient from "./AdminUsersClient";
import { resolveOpenMaicEmbed } from "@/lib/openmaic-embed";

/**
 * Fork: a server component around the users page, for one value the client
 * cannot read -- where the Course Studio is embedded. A purge from the bin
 * (admin design §4, Phase 2) removes the account's studio data first, and the
 * browser calls the studio's admin route on the same origin through the
 * gatekeeper, so the page needs the studio's path. It comes from
 * `DEEPTUTOR_OPENMAIC_URL` at request time, the same way the course-studio
 * page reads it, which is why this is `force-dynamic`: rendered once at build
 * it would freeze "unconfigured" into the image.
 */
export const dynamic = "force-dynamic";

export default function AdminUsersPage() {
  const { url, sameOrigin } = resolveOpenMaicEmbed();
  return <AdminUsersClient studioBase={sameOrigin ? url : ""} />;
}
