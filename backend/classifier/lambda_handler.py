"""InstrumentClassifier Lambda handler."""

import json
import asyncio
import logging
from typing import List, Dict, Any

try:
    from .agent import tag_instruments, classification_to_db_format
    from .observability import observe
except ImportError:
    from agent import tag_instruments, classification_to_db_format
    from observability import observe

# Configure logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

async def process_instruments(instruments: List[Dict[str, str]]) -> Dict[str, Any]:
    """
    Process and classify instruments asynchronously.
    
    Args:
        instruments: List of instruments to classify
        
    Returns:
        Processing results
    """
    # Run the classification
    logger.info(f"Classifying {len(instruments)} instruments")
    classifications = await tag_instruments(instruments)
    
    records = [classification_to_db_format(item) for item in classifications]
    
    # Prepare response (convert Pydantic models to dicts)
    return {
        'tagged': len(classifications),
        'updated': [],
        'errors': [],
        'persistence': 'not_applicable',
        'classifications': [
            {
                'symbol': c.symbol,
                'name': c.name,
                'type': c.instrument_type,
                'current_price': float(c.current_price),
                'asset_class': c.allocation_asset_class,
                'regions': c.allocation_regions,
                'sectors': c.allocation_sectors,
            }
            for c in records
        ]
    }

def lambda_handler(event, context):
    """
    Lambda handler for instrument tagging.

    Expected event format:
    {
        "instruments": [
            {"symbol": "VTI", "name": "Vanguard Total Stock Market ETF"},
            ...
        ]
    }
    """
    # Wrap entire handler with observability context
    with observe():
        try:
            # Parse the event
            instruments = event.get('instruments', [])

            if not instruments:
                return {
                    'statusCode': 400,
                    'body': json.dumps({'error': 'No instruments provided'})
                }

            # Process all instruments in a single async context
            result = asyncio.run(process_instruments(instruments))

            return {
                'statusCode': 200,
                'body': json.dumps(result)
            }

        except Exception as e:
            logger.error(f"Lambda handler error: {e}")
            return {
                'statusCode': 500,
                'body': json.dumps({'error': str(e)})
            }
