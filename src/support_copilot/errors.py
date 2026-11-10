class CopilotError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 503) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.trace: dict | None = None
        self.retrieved_passages: list[dict] = []
        self.retrieval_completed = False
        self.candidate_draft: dict | None = None
