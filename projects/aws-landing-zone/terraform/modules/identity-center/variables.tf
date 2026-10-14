variable "group_ids" {
  description = "Identity store group name -> group ID. Groups come from the identity provider (SCIM) or are created outside this module; no users or groups are created here."
  type        = map(string)

  validation {
    condition     = alltrue([for id in values(var.group_ids) : can(regex("^([0-9a-f]{10}-)?[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", id))])
    error_message = "group_ids values must be identity store group IDs (a UUID, optionally prefixed by a 10-character store ID)."
  }
}

variable "account_ids" {
  description = "Account key -> account ID (the organization module's account_ids output, plus management if needed)."
  type        = map(string)

  validation {
    condition     = alltrue([for id in values(var.account_ids) : can(regex("^[0-9]{12}$", id))])
    error_message = "account_ids values must be 12-digit account IDs."
  }
}

variable "assignments" {
  description = "Group name -> account key -> permission set names. Example: { platform-admins = { shared-services = [\"AdministratorAccess\"] } }."
  type        = map(map(list(string)))

  validation {
    condition = alltrue(flatten([
      for g, accounts in var.assignments : [
        for a, sets in accounts : [for s in sets : contains(["AdministratorAccess", "PowerUserAccess", "ReadOnlyAccess", "BillingAccess"], s)]
      ]
    ]))
    error_message = "Permission set names must be AdministratorAccess, PowerUserAccess, ReadOnlyAccess or BillingAccess."
  }
}

variable "session_durations" {
  description = "Permission set -> ISO 8601 session duration. Admin is deliberately short."
  type        = map(string)
  default = {
    AdministratorAccess = "PT1H"
    PowerUserAccess     = "PT4H"
    ReadOnlyAccess      = "PT8H"
    BillingAccess       = "PT4H"
  }

  validation {
    condition     = alltrue([for d in values(var.session_durations) : can(regex("^PT([1-9]|1[0-2])H$", d))])
    error_message = "Session durations must be PT1H to PT12H."
  }
}

variable "tags" {
  description = "Tags for the permission sets."
  type        = map(string)
  default     = {}
}
