import pathlib
import sys
import unittest
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from parser import Parser
from runtime import Runtime

class PrototypeTests(unittest.TestCase):
    def test_arithmetic_and_functions(self):
        src = """
        fn twice(x) { return x * 2; }
        print(twice(6));
        """
        p = Parser(src).parse()
        r = Runtime(p)
        self.assertEqual(r.run(), [12])

    def test_if_else(self):
        src = """
        fn choose(x) {
          if (x > 3) { return 1; } else { return 0; }
        }
        print(choose(5));
        print(choose(1));
        """
        p = Parser(src).parse()
        r = Runtime(p)
        self.assertEqual(r.run(), [1, 0])

    def test_while(self):
        src = """
        fn count() {
          let i = 0;
          while (i < 4) { i = i + 1; }
          return i;
        }
        print(count());
        """
        p = Parser(src).parse()
        r = Runtime(p)
        self.assertEqual(r.run(), [4])

if __name__ == "__main__":
    unittest.main()
