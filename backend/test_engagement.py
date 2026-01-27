import os
import sys
import unittest
import asyncio

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.engagement_framer import EngagementFramer

class TestEngagementFramer(unittest.TestCase):
    def setUp(self):
        # Mock DexTrader is not needed for simple generation tests
        self.framer = EngagementFramer()

    def test_comment_generation(self):
        """Verify that generated comments are diverse and formatted correctly."""
        comments = [self.framer.generate_random_comment() for _ in range(50)]
        
        # Check basic properties
        for comment in comments:
            self.assertTrue(len(comment) > 0)
            self.assertIsInstance(comment, str)
            
        # Check for diversity (shouldn't all be the same)
        unique_comments = set(comments)
        self.assertGreater(len(unique_comments), 10, "Comments are not diverse enough")
        
        print("\n--- SAMPLE GENERATED COMMENTS ---")
        for i in range(5):
            print(f"{i+1}: {comments[i]}")

if __name__ == "__main__":
    unittest.main()
