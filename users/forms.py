#pylint: disable=all
from django import forms
from django.contrib.auth import get_user_model

User = get_user_model()


class UserProfileForm(forms.ModelForm):
    class Meta:
        model = User
        fields = [
            'first_name',
            'last_name',
            'username',
            'phone',
            'address',
            'gender',
            'date_of_birth',
        ]
        widgets = {
            'first_name': forms.TextInput(attrs={
                'class': 'form-input',
                'placeholder': 'Enter first name',
            }),
            'last_name': forms.TextInput(attrs={
                'class': 'form-input',
                'placeholder': 'Enter last name',
            }),
            'username': forms.TextInput(attrs={
                'class': 'form-input',
                'placeholder': 'Choose a unique username',
            }),
            'phone': forms.TextInput(attrs={
                'class': 'form-input',
                'placeholder': '+1 (555) 000-0000',
                'type': 'tel',
            }),
            'address': forms.Textarea(attrs={
                'class': 'form-textarea',
                'placeholder': 'Enter your address',
                'rows': 3,
            }),
            'gender': forms.Select(attrs={
                'class': 'form-select',
            }),
            'date_of_birth': forms.DateInput(attrs={
                'class': 'form-input',
                'type': 'date',
            }),
        }

    def clean_username(self):
        username = self.cleaned_data.get('username')
        if username:
            # Check if username is already taken (excluding current user)
            existing_user = User.objects.filter(
                username=username
            ).exclude(pk=self.instance.pk).first()
            if existing_user:
                raise forms.ValidationError('This username is already taken.')
        return username


