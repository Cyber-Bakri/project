#!/usr/bin/env python3

import os
import sys
import json
import requests
from datetime import datetime, timedelta
import urllib3

# Disable SSL warnings - use only in development or with self-signed certificates
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

def get_env_var(var_name, default=None, required=False):
    """Get environment variable or return default value"""
    value = os.environ.get(var_name, default)
    if required and value is None:
        print(f"ERROR: Required environment variable {var_name} is not set.")
        sys.exit(1)
    return value

def get_date_range():
    """Calculate the date range"""
    present_date = datetime.now()
    end_date = present_date + timedelta(days=90)
    start_date = present_date - timedelta(days=60)
    
    start_date_str = start_date.strftime("%Y-%m-%dT00:00:00Z")
    end_date_str = end_date.strftime("%Y-%m-%dT23:59:59Z")
    
    return start_date_str, end_date_str

def query_elasticsearch():
    """Query Elasticsearch for P1 and P2 priority items only"""
    
    # Get environment variables
    es_host = get_env_var("ES_HOST", required=True)
    es_index = get_env_var("ES_INDEX", required=True)
    
    # date range for reference
    start_date, end_date = get_date_range()
    print(f"Fetching P1/P2 priority data from {start_date} to {end_date}")
    
    # Get authentication if provided
    username = get_env_var("ES_USERNAME", "")
    password = get_env_var("ES_PASSWORD", "")
    auth = None
    if username and password:
        auth = (username, password)
    
    # Build the search URL
    search_url = f"{es_host}/{es_index}/_search"
    
    # Query only for P1 and P2 priority items, sort by issue types
    query = {
        "query": {
            "bool": {
                "must": [
                    {
                        "terms": {
                            "priority.keyword": ["P1", "P2"]
                        }
                    }
                ]
            }
        },
        "aggs": {
            "by_priority": {
                "terms": {
                    "field": "priority.keyword",
                    "size": 10
                },
                "aggs": {
                    "by_issue_type": {
                        "terms": {
                            "field": "issueType.keyword",
                            "size": 100
                        },
                        "aggs": {
                            "by_app_code": {
                                "terms": {
                                    "field": "appCode.keyword",
                                    "size": 1000
                                }
                            }
                        }
                    }
                }
            },
            "all_issue_types": {
                "terms": {
                    "field": "issueType.keyword",
                    "size": 100
                }
            },
            "all_app_codes": {
                "terms": {
                    "field": "appCode.keyword",
                    "size": 1000
                }
            }
        },
        "sort": [
            {"priority.keyword": {"order": "asc"}},
            {"issueType.keyword": {"order": "asc"}},
            {"appCode.keyword": {"order": "asc"}}
        ],
        "size": 10000  # Get all matching documents
    }
    
    headers = {
        "Content-Type": "application/json"
    }
    
    try:
        response = requests.post(
            search_url,
            headers=headers,
            json=query,
            auth=auth,
            verify=False
        )
        
        if response.status_code == 200:
            result = response.json()
            
            priority_summary = {}
            all_issue_types = set()
            all_app_codes = set()
            
            if "aggregations" in result:
                # Process priority aggregations
                if "by_priority" in result["aggregations"]:
                    for priority_bucket in result["aggregations"]["by_priority"]["buckets"]:
                        priority = priority_bucket["key"]
                        priority_count = priority_bucket["doc_count"]
                        
                        priority_summary[priority] = {
                            "total_count": priority_count,
                            "issue_types": {}
                        }
                        
                        if "by_issue_type" in priority_bucket:
                            for issue_type_bucket in priority_bucket["by_issue_type"]["buckets"]:
                                issue_type = issue_type_bucket["key"]
                                issue_count = issue_type_bucket["doc_count"]
                                all_issue_types.add(issue_type)
                                
                                priority_summary[priority]["issue_types"][issue_type] = {
                                    "count": issue_count,
                                    "app_codes": []
                                }
                                
                                if "by_app_code" in issue_type_bucket:
                                    for app_bucket in issue_type_bucket["by_app_code"]["buckets"]:
                                        app_code = app_bucket["key"]
                                        app_count = app_bucket["doc_count"]
                                        all_app_codes.add(app_code)
                                        
                                        priority_summary[priority]["issue_types"][issue_type]["app_codes"].append({
                                            "app_code": app_code,
                                            "count": app_count
                                        })
                
                # Get all issue types for reference
                if "all_issue_types" in result["aggregations"]:
                    for bucket in result["aggregations"]["all_issue_types"]["buckets"]:
                        all_issue_types.add(bucket["key"])
                
                # Get all app codes for reference
                if "all_app_codes" in result["aggregations"]:
                    for bucket in result["aggregations"]["all_app_codes"]["buckets"]:
                        all_app_codes.add(bucket["key"])
            
            # Save results
            output_file = get_env_var("OUTPUT_FILE", "")
            if output_file:
                # Add our processing summary to the result
                result["processing_summary"] = {
                    "priority_breakdown": priority_summary,
                    "total_issue_types": list(sorted(all_issue_types)),
                    "total_app_codes": list(sorted(all_app_codes)),
                    "date_range": {
                        "start_date": start_date,
                        "end_date": end_date
                    }
                }
                
                with open(output_file, 'w') as f:
                    json.dump(result, f, indent=2)
                
                print(f"Query results saved to {output_file}")
                
                # Print summary
                hits = result.get("hits", {}).get("hits", [])
                total = result.get("hits", {}).get("total", {}).get("value", 0)
                print(f"Found {total} total documents with P1/P2 priority")
                print(f"Retrieved {len(hits)} documents")
                
                print(f"\nPriority Breakdown:")
                for priority in sorted(priority_summary.keys()):
                    print(f"  {priority}: {priority_summary[priority]['total_count']} issues")
                    for issue_type in sorted(priority_summary[priority]['issue_types'].keys()):
                        count = priority_summary[priority]['issue_types'][issue_type]['count']
                        app_count = len(priority_summary[priority]['issue_types'][issue_type]['app_codes'])
                        print(f"    {issue_type}: {count} issues across {app_count} applications")
                
                print(f"\nAll Issue Types found: {len(all_issue_types)}")
                print(f"Issue Types: {', '.join(sorted(all_issue_types))}")
                print(f"Applications affected: {len(all_app_codes)}")
                
                if hits:
                    print(f"\nSample document fields:")
                    sample_source = hits[0].get("_source", {})
                    print(f"Available fields: {list(sample_source.keys())}")
                else:
                    print("No documents returned")
        else:
            print(f"ERROR: Elasticsearch query failed with status {response.status_code}")
            print(f"Response: {response.text}")
            return False
        
        return True
        
    except Exception as e:
        print(f"ERROR: Failed to query Elasticsearch: {str(e)}")
        
        # Still create an empty output file to avoid failing the pipeline
        output_file = get_env_var("OUTPUT_FILE", "")
        if output_file:
            empty_result = {
                "hits": {"hits": [], "total": {"value": 0}},
                "aggregations": {},
                "processing_summary": {
                    "priority_breakdown": {},
                    "total_issue_types": [],
                    "total_app_codes": [],
                    "date_range": {
                        "start_date": get_date_range()[0],
                        "end_date": get_date_range()[1]
                    }
                },
                "error": str(e)
            }
            try:
                with open(output_file, 'w') as f:
                    json.dump(empty_result, f, indent=2)
                print(f"Created empty result file at {output_file} due to error")
            except Exception as file_error:
                print(f"Failed to create output file: {file_error}")
        
        return False

if __name__ == "__main__":
    success = query_elasticsearch()
    if success:
        print("Data fetch completed successfully")
        sys.exit(0)
    else:
        print("Data fetch failed")
        sys.exit(1) 
