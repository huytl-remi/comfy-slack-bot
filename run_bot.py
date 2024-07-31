import os
import sys
import asyncio

# Set the PYTHONPATH to the src directory
current_dir = os.path.dirname(os.path.abspath(__file__))
src_path = os.path.join(current_dir, 'src')
sys.path.append(src_path)

# Now we can import and run the main script
from src.main import main

if __name__ == "__main__":
    asyncio.run(main())
