from django import forms

class ExcelUploadForm(forms.Form):
    file = forms.FileField(label='Upload a file')
    #enable_auto_split = forms.BooleanField(
        # label='Enable automatic splitting of misclassified entities',
        # required=False,
        # initial=False,
        #help_text='If checked, entities will be automatically moved between individual and corporate categories based on business keywords. If unchecked, you will be prompted to manually verify any potential misclassifications.'
    #)