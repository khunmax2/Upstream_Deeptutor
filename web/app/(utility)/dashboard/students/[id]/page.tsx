"use client";

import { useParams } from "next/navigation";

import StudentDetail from "@/components/dashboard/StudentDetail";

/** Fork: one student's learning evidence (school roles, Phase 3b). */
export default function StudentPage() {
  const params = useParams<{ id: string }>();
  return <StudentDetail studentId={String(params.id || "")} />;
}
