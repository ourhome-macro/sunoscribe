export interface PublicArtifactResponse {
  id: string
  artifact_type: string
  status: string | null
  filename: string | null
  mime_type: string | null
  file_size_bytes: number | null
  checksum: string | null
  created_at: string | null
}

export interface ArtifactSummaryGroup {
  label: string
  artifacts: PublicArtifactResponse[]
}
