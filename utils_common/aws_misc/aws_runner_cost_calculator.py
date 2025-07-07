def calculate_monthly_app_runner_cost(
    vcpu: float,
    memory_gb: float,
    provisioned_hours_per_day: float,
    active_hours_per_day: float,
    cost_provisioned_per_gb_hour: float,
    cost_active_per_vcpu_hour: float,
    cost_active_per_gb_hour: float,
    days_per_month: int = 30,
) -> float:
    """
    Calculate the monthly cost for an AWS App Runner service.

    Parameters:
    - vcpu: Number of vCPUs allocated (e.g., 0.5, 1, 2)
    - memory_gb: Amount of memory in GB (e.g., 2, 4)
    - provisioned_hours_per_day: Hours per day the container is provisioned (warm but idle)
    - active_hours_per_day: Hours per day the container is actively servicing requests
    - cost_provisioned_per_gb_hour: AWS rate for provisioned memory ($/GB-hour)
    - cost_active_per_vcpu_hour: AWS rate for active CPU usage ($/vCPU-hour)
    - cost_active_per_gb_hour: AWS rate for active memory usage ($/GB-hour)
    - days_per_month: Number of days in the billing month (default: 30)

    Returns:
    - Monthly cost in USD
    """
    # Daily provisioned memory cost (warm but idle)
    daily_provisioned_cost = (
        provisioned_hours_per_day * memory_gb * cost_provisioned_per_gb_hour
    )

    # Daily active costs:
    daily_active_cpu_cost = active_hours_per_day * vcpu * cost_active_per_vcpu_hour
    daily_active_memory_cost = (
        active_hours_per_day * memory_gb * cost_active_per_gb_hour
    )

    # Total daily cost
    total_daily_cost = (
        daily_provisioned_cost + daily_active_cpu_cost + daily_active_memory_cost
    )

    # Monthly cost
    monthly_cost = total_daily_cost * days_per_month
    return monthly_cost


# Example usage based on your setup:
if __name__ == "__main__":
    vcpu = 0.5
    memory_gb = 2
    provisioned_hours_per_day = 16  # warmed
    active_hours_per_day = 12  # processing
    cost_provisioned_per_gb_hour = 0.007
    cost_active_per_vcpu_hour = 0.064
    cost_active_per_gb_hour = 0.007
    days_per_month = 30

    cost = calculate_monthly_app_runner_cost(
        vcpu,
        memory_gb,
        provisioned_hours_per_day,
        active_hours_per_day,
        cost_provisioned_per_gb_hour,
        cost_active_per_vcpu_hour,
        cost_active_per_gb_hour,
        days_per_month,
    )
    print(f"Estimated monthly cost: ${cost:.2f}")
