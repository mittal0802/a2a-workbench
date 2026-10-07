"""Reassembly of streamed artifacts."""

from a2a.types import Artifact, TaskArtifactUpdateEvent


class ArtifactAssembler:
    """Builds complete artifacts from ``TaskArtifactUpdateEvent`` chunks.

    A chunk with ``append`` set extends the parts of the artifact with the same
    task and artifact id; any other chunk replaces it. Returned artifacts are
    independent copies.
    """

    def __init__(self) -> None:
        self._artifacts: dict[tuple[str, str], Artifact] = {}

    def seed(self, task_id: str, artifact: Artifact) -> None:
        """Record an artifact already known from a Task snapshot."""
        copy = Artifact()
        copy.CopyFrom(artifact)
        self._artifacts[(task_id, artifact.artifact_id)] = copy

    def apply(self, event: TaskArtifactUpdateEvent) -> Artifact:
        """Merge ``event`` into the assembled artifact and return a copy of the result."""
        key = (event.task_id, event.artifact.artifact_id)
        current = self._artifacts.get(key)
        merged = Artifact()
        if event.append and current is not None:
            merged.CopyFrom(current)
            merged.parts.extend(event.artifact.parts)
            if event.artifact.name:
                merged.name = event.artifact.name
            if event.artifact.description:
                merged.description = event.artifact.description
            merged.metadata.update(event.artifact.metadata)
            merged.extensions.extend(
                e for e in event.artifact.extensions if e not in merged.extensions
            )
        else:
            merged.CopyFrom(event.artifact)
        self._artifacts[key] = merged
        result = Artifact()
        result.CopyFrom(merged)
        return result
