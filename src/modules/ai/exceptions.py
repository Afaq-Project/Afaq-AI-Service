class OpportunityNotFoundError(Exception):
    code = "opportunity_not_found"
    status_code = 404

    def __init__(self, opportunity_id: str) -> None:
        super().__init__(f"opportunity {opportunity_id} not found")
        self.opportunity_id = opportunity_id
