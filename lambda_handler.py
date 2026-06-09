"""
AWS Lambda handler for SR Pipeline
Runs on: python3.12 Bedrock with IAM roles
"""

import json
import subprocess
import sys
import os
import boto3

s3 = boto3.client('s3')

def lambda_handler(event, context):
    """
    Lambda entry point for SR Pipeline
    """

    # Parameters from event
    query = event.get('query', '("Cancer Survivors"[MeSH]) AND ("Exercise"[MeSH] OR "Physical Activity"[MeSH])')
    inclusion = event.get('inclusion', 'Adult cancer survivors, exercise-based interventions, RCT or cohort studies')
    exclusion = event.get('exclusion', 'Animal studies, pediatric, non-English')
    outcomes = event.get('outcomes', 'Quality of Life, Fatigue, Physical Function')
    bucket = event.get('bucket', 'sr-pipeline-1780976872')

    print(f"Starting SR Pipeline")
    print(f"Query: {query}")

    try:
        # Install dependencies
        print("Installing dependencies...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", "-r", "requirements.txt"])

        # Download scripts from S3
        print("Downloading scripts...")
        for script in ['sr_search.py', 'sr_screening.py', 'sr_data_extraction.py', 'sr_pipeline.py']:
            s3.download_file(bucket, script, f'/tmp/{script}')

        # Run pipeline
        print("Running pipeline...")
        result = subprocess.run([
            sys.executable, '/tmp/sr_pipeline.py',
            '--query', query,
            '--inclusion', inclusion,
            '--exclusion', exclusion,
            '--outcomes', outcomes,
            '--output-dir', '/tmp/output',
            '--skip-search'
        ], capture_output=True, text=True, timeout=3600)

        print(result.stdout)
        if result.stderr:
            print("Errors:", result.stderr)

        # Upload results to S3
        print("Uploading results...")
        subprocess.run(['aws', 's3', 'sync', '/tmp/output', f's3://{bucket}/output/'])

        return {
            'statusCode': 200,
            'body': json.dumps({
                'message': 'Pipeline completed',
                'output_bucket': bucket,
                'output_path': 's3://{bucket}/output/'
            })
        }

    except Exception as e:
        print(f"Error: {str(e)}")
        return {
            'statusCode': 500,
            'body': json.dumps({'error': str(e)})
        }
