# Taxonomy — OpenMed raw labels → scrub action (step 5)

Step 5 maps each NER span’s raw label to **blank**, **synth**, **ignore**, or
**defer-to-script**. Unknown labels → **ignore**.

**Step 4 prepare (not taxonomy):** caret→space; optional `Keyword: value` wrap.
**Step 6:** `ner_residual_cleanup` strips dangling `for` / `FORFILE` / month+year
tokens after blanks. No keyword skip lists, no radiology deny-lists, no whole-tag
keyword wipe in taxonomy.

## Actions


| raw_label                                                                   | action          |
| --------------------------------------------------------------------------- | --------------- |
| FIRST_NAME / LAST_NAME / MIDDLE_NAME / NAME / PERSON / PATIENT / DOCTOR     | blank           |
| USER_NAME / USERNAME                                                        | blank           |
| STREET_ADDRESS / STREET / ADDRESS / CITY / STATE / ZIP / POSTCODE / COUNTRY | blank           |
| PHONE / PHONE_NUMBER / FAX_NUMBER                                           | blank           |
| EMAIL / EMAIL_ADDRESS                                                       | blank           |
| CUSTOMER_ID / CREDIT_DEBIT_CARD / ACCOUNT_NUMBER / EMPLOYEE_ID / … IDs      | blank           |
| HOSPITAL / FAC                                                              | blank           |
| DATE / DOB / DATE_OF_BIRTH                                                  | defer-to-script |
| COMPANY_NAME                                                                | ignore          |
| anything else                                                               | ignore          |


Source of truth: `taxonomy.py` (`DEFAULT_ACTIONS`).