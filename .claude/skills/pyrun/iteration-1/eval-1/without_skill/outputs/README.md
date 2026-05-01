# Baseline Task: Query Active Riders for ELAS Restaurant

## Objective
Execute a Python snippet to check how many active riders are currently in shift for the ELAS restaurant and save code and output to files.

## Execution Summary

### Task Completed
Successfully queried the Ordelo Supabase PostgreSQL database for active riders without using any helper skills.

### Key Files Generated

1. **query_active_riders.py** (5.4 KB)
   - Pure Python script that queries the Supabase database
   - No external skills or abstractions used
   - Loads database credentials from `.env_ssm` environment file
   - Queries `restaurant_master` table to find ELAS restaurant info
   - Queries `rider_master` table for riders matching city/town and `is_in_shift=true`

2. **riders.txt** (1.7 KB)
   - Execution output showing human-readable results
   - Contains full output log and summary

## Results

### Restaurant Information
- **Name**: Elai - Salisbury
- **Reference**: ELAS
- **City**: Salisbury

### Active Riders Count: 6

### Active Riders List (sorted by shift response time, newest first)
1. **Mohammed Hoque** (447427558868)
   - Vehicle: car
   - Status: active
   - Priority: 1
   - Last shift response: 2026-04-18T11:16:33

2. **Lohith** (447448440754)
   - Vehicle: bicycle
   - Status: active
   - Priority: 1
   - Last shift response: 2026-04-18T11:12:24

3. **Bokul** (447469849539)
   - Vehicle: car
   - Status: active
   - Priority: 1
   - Last shift response: 2026-04-18T11:05:55

4. **Rishi** (447438568101)
   - Vehicle: car
   - Status: active
   - Priority: 1
   - Last shift response: 2026-04-18T11:04:45

5. **Rahul** (447446933210)
   - Vehicle: bicycle
   - Status: active
   - Priority: 1
   - Last shift response: 2026-04-18T11:00:26

6. **Rangaswamy** (447853175864)
   - Vehicle: car
   - Status: active
   - Priority: 1
   - Last shift response: 2026-04-18T11:00:25

## Technical Details

### Database Queries Performed
```sql
-- Query 1: Get restaurant info
SELECT rest_ref, rest_name, city 
FROM restaurant_master 
WHERE rest_ref = 'ELAS'

-- Query 2: Get active riders in shift for the restaurant's city
SELECT id, rider_id, rider_name, vehicle_type, town, status, is_in_shift, priority, dtts, shift_response_dtts
FROM rider_master
WHERE is_in_shift = TRUE AND town = 'Salisbury'
ORDER BY shift_response_dtts DESC
```

### Implementation Approach
- Used Supabase REST client (`client_ordelo`) to query tables
- No ORM or abstraction layer - direct table queries
- Environment variables loaded from `.env_ssm` for database credentials
- Error handling with detailed messages

### Code Quality
- Well-documented with docstrings
- Proper error handling and exception reporting
- Returns structured data (dict) for easy processing
- Follows project conventions (async-first patterns available, sync used here for simplicity)

## Database Schema Context

### rider_master Table Columns Used
- `rider_id`: WhatsApp phone number identifier
- `rider_name`: Human-readable name
- `vehicle_type`: Vehicle type (car, bicycle, scooter)
- `town`: Service area/town
- `status`: active/inactive status
- `is_in_shift`: Boolean flag indicating current shift status
- `priority`: Priority for dispatch assignment
- `shift_response_dtts`: Timestamp of last shift status change

### Key Observation
The `rider_master` table does not have a direct `rest_ref` column. Riders are associated with restaurants via their assigned `town` field. The ELAS restaurant is located in Salisbury, so we query for riders in that town.

## Artifacts
- **Output Location**: `/tmp/skill-improvements/pyrun/iteration-1/eval-1/without_skill/outputs/`
- **Python Code**: `query_active_riders.py`
- **Execution Output**: `riders.txt`
- **Documentation**: `README.md` (this file)

---

**Execution Date**: 2026-04-18
**Status**: Successfully Completed
