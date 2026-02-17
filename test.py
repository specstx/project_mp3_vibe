# tests 

class DataFactory:
    def __init__(self, seed=42):
        self.state = seed
        self.vowels = "aeiou"
        self.consonants = "bcdfghjlmnprstvw"

    def _crank(self):
        # 32-bit LGC for deterministic chaos
        self.state = (1664525 * self.state + 1013904223) % (2**32)
        return self.state

    def build_list(self, size, sort=False, scale=100, mode="int", seed=None):
        """
        The laboratory method for generating lists.
        - sort=True: Prepare the list for Binary Search Sniping.
        - mode='word': Generate phonetic strings instead of numbers.
        """
        output = []
        for _ in range(size):
            if mode == "word":
                word = ""
                for i in range(6):
                    word += self.consonants[self._crank() % len(self.consonants)] if i % 2 == 0 \
                            else self.vowels[self._crank() % len(self.vowels)]
                output.append(word.capitalize())
            else:
                output.append(self._crank() % scale)
        
        if sort:
            output.sort()
        return output

class Warehouse:
    def __init__(self, factory_instance):
        self.factory = factory_instance
        self.keys = []

    def build_stack(self, rows=500, sort=False):
        """ Creates 500 dicts with 5 keys each using the linked factory. """
        # Lock 5 random keys once to define the schema
        if not self.keys:
            self.keys = [k.lower() for k in self.factory.build_list(5, mode="word")]
        
        stack = []
        for _ in range(rows):
            record = {}
            for i, key in enumerate(self.keys):
                # Alternate Word/Number/Word/Number/Word for a deep data stack
                if i % 2 == 0:
                    record[key] = self.factory.build_list(1, mode="word")[0]
                else:
                    record[key] = self.factory.build_list(1, scale=1000)[0]
            stack.append(record)
        if sort:
            stack = sorted(stack, key=lambda x: x[self.keys[0]])
            return stack, self.keys[0]
        return stack



# 1. Start the machines
df = DataFactory(seed=42)
plant = Warehouse(df)

# 2. Need raw numbers for your Binary Search?
numbers = df.build_list(1000) # Simple list
numbers2 = df.build_list(10, sort=True, seed=77)
numbers3 = df.build_list(10, sort=True)

# 3. Need the "Deep Stack" of 500 dictionaries?
# warehouse = plant.build_stack(500) # List of dicts with 5 keys each
warehouse, whkey = plant.build_stack(100, sort=True) 

print(numbers2)
print(numbers3)
#[print(*(f"{k}: {v}" for k, v in d.items()), sep=", ") for d in warehouse]
#print(whkey)
#print(warehouse)
""" For sorted data Binary search low mid high pro level search mid = low + (high - low) // 2  mid == target (end) or mid < target: low = mid + 1 or high = mid -1"""
"""
    Performs binary search to find the target in the sorted array arr.
    
    Args:
        arr (list): A sorted list of comparable elements.
        target: The value to search for.
    
    Returns:
        int: The index of the target if found, otherwise -1.
    """

def binary_search(arr, target, key=None):
    
    low = 0
    high = len(arr) - 1

    while low <= high:
        # The key formula to calculate the middle index
        mid = low + (high - low) // 2
        
        # The Universal Lens: 
        # If key is provided, we're sniping a dict. If not, we're sniping a raw list.
        current_val = arr[mid][key] if key is not None else arr[mid]
        
        if current_val == target:
            return mid  # Target found
        elif current_val < target:
            low = mid + 1  # Target is in the right half
        else:
            high = mid - 1 # Target is in the left half
            
    return -1 # Target not found

# --- Example Usage ---
target_value = "Pisivi"
#target_value = 96
# binary test block
#result_index = binary_search(numbers2, target_value)
result_index = binary_search(warehouse, target_value, whkey)
if result_index != -1:
    print(f"Element {target_value} found at index: {result_index}")
else:
    print(f"Element {target_value} not found in the list.")

"""
target_value_not_found = 197
result_index_not_found = binary_search(numbers2, target_value_not_found)
if result_index_not_found == -1:
    print(f"Element {target_value_not_found} not found.")

"""