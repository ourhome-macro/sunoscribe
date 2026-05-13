export interface PublicArtifactResponse {
  id: string
  artifact_type: string
  status: string | null
  filename: string | null
  mime_type: string | null
  file_size_bytes: number | null
  checksum: string | null
  created_at: string | null
  metadata?: {
    export_scope?: string | null
    quality_gate_status?: string | null
    quality_failed_checks?: string[]
    diagnostic_message?: string | null
    kind?: string | null
    report_status?: string | null
  } | null
}

export interface ArtifactSummaryGroup {
  label: string
  artifacts: PublicArtifactResponse[]
}
