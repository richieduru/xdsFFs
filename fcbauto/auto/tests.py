from django.test import TestCase
from .views import try_convert_to_float


class TryConvertToFloatTest(TestCase):
    def test_none_and_empty(self):
        """Test None and empty string cases"""
        self.assertEqual(try_convert_to_float(None), '')
        self.assertEqual(try_convert_to_float(''), '')
        self.assertEqual(try_convert_to_float('   '), '')

    def test_valid_numbers(self):
        """Test valid numeric strings"""
        self.assertEqual(try_convert_to_float('123.45'), '123.45')
        self.assertEqual(try_convert_to_float('42'), '42.00')
        self.assertEqual(try_convert_to_float('0.001'), '0.00')
        self.assertEqual(try_convert_to_float('1000000.50'), '1000000.50')

    def test_mixed_alphanumeric(self):
        """Test strings with mixed alphanumeric characters"""
        self.assertEqual(try_convert_to_float('price: $123.45'), '123.45')
        self.assertEqual(try_convert_to_float('100 apples'), '100.00')
        self.assertEqual(try_convert_to_float('123.45 kg'), '123.45')
        self.assertEqual(try_convert_to_float('abc123.45xyz'), '123.45')

    def test_currency_and_symbols(self):
        """Test strings with currency symbols and other non-numeric characters"""
        self.assertEqual(try_convert_to_float('$1,234.56'), '1234.56')
        self.assertEqual(try_convert_to_float('€2,500.75'), '2500.75')
        self.assertEqual(try_convert_to_float('£100.50'), '100.50')
        self.assertEqual(try_convert_to_float('1,000,000.00'), '1000000.00')

    def test_edge_cases(self):
        """Test edge cases and special values"""
        self.assertEqual(try_convert_to_float('1e6'), '1000000.00')
        self.assertEqual(try_convert_to_float('-123.45'), '-123.45')
        self.assertEqual(try_convert_to_float('123.45.67'), '123.45')
        self.assertEqual(try_convert_to_float('123..45'), '123.00')
        self.assertEqual(try_convert_to_float('123.45.67.89'), '123.45')

    def test_invalid_inputs(self):
        """Test inputs that should return original value"""
        self.assertEqual(try_convert_to_float('abc'), 'abc')
        self.assertEqual(try_convert_to_float('123abc456'), '123abc456')
        self.assertEqual(try_convert_to_float('---'), '---')
        self.assertEqual(try_convert_to_float('123.45.67.89.01'), '123.45.67.89.01')
        self.assertEqual(try_convert_to_float('NaN'), 'NaN')
        self.assertEqual(try_convert_to_float('Infinity'), 'Infinity')

    def test_unicode_numbers(self):
        """Test strings containing unicode numbers"""
        self.assertEqual(try_convert_to_float('¼'), '¼')  # Should return original since it's not a standard float
        self.assertEqual(try_convert_to_float('½'), '½')
        self.assertEqual(try_convert_to_float('⅓'), '⅓')
        self.assertEqual(try_convert_to_float('1.5½'), '1.5½')

    def test_whitespace_handling(self):
        """Test handling of whitespace"""
        self.assertEqual(try_convert_to_float('  123.45  '), '123.45')
        self.assertEqual(try_convert_to_float('\n123.45\n'), '123.45')
        self.assertEqual(try_convert_to_float('\t123.45\t'), '123.45')
        self.assertEqual(try_convert_to_float('  123.45  \n'), '123.45')

    def test_special_characters(self):
        """Test strings with special characters"""
        self.assertEqual(try_convert_to_float('123.45%'), '123.45')
        self.assertEqual(try_convert_to_float('123.45+'), '123.45')
        self.assertEqual(try_convert_to_float('123.45-'), '123.45')
        self.assertEqual(try_convert_to_float('123.45*'), '123.45')
        self.assertEqual(try_convert_to_float('123.45/'), '123.45')
