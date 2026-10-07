# Data requests: letters ready to send

TenderLens does not scrape award data that is CAPTCHA-gated, and it does not reuse data
whose terms require permission first (`docs/BID_ADVISOR.md` section 2,
`docs/SOURCE_NOTES.md` "Award data"). These four letters ask the owners for that
permission. Fill in the placeholders, check every address against the recipient's official
"Contact us" page on the day you send, and keep a copy of each letter and every reply in
`docs/` or the company drive. Facts cited were checked on 7 October 2026.

| # | To | Asks for | Unlocks |
|---|---|---|---|
| A | GeM SPV | Written permission to reuse BidPlus "Bid/RA results" | All sellers' prices and ranks, 3.38M awarded bids/RAs since 2018 (goods, services) |
| B | Department of Expenditure (PPD) and NIC | Bulk/API access to CPPP and GePNIC Award-of-Contract (AOC) data under an MoU | Contract value, bids received, selected bidder, for central and state works |
| C | Any public authority (RTI) | AOC and bid data for one department and period | The same data, one department at a time, while B is pending |
| D | Academic authors | A licence that allows commercial use of bid-level PMGSY data | Every bid on rural road works, 2000-2017 |

Placeholders: `[Founder name]`, `[Designation]`, `[Company]`, `[CIN]`, `[Address]`,
`[Email]`, `[Phone]`, `[Website]`, `[Date]`.

---

## A. GeM SPV: permission to reuse BidPlus results

**To:** The Chief Executive Officer, Government e-Marketplace (GeM SPV), Ministry of Commerce
and Industry, Government of India, [GeM SPV address from gem.gov.in]
**Copy:** [GeM data or API partnership contact, if one is listed]
**Subject:** Request for written permission to reuse public BidPlus "Bid/RA results" data, with attribution

Dear Sir or Madam,

[Company] ([CIN]) runs TenderLens ([Website]), a service that helps Indian contractors and
MSEs find public tenders and prepare competitive bids. We are writing to ask for GeM SPV's
written permission, as the GeM Copyright Policy requires, to reuse data that BidPlus
already publishes without login.

**What we ask to reuse.** For bids and reverse auctions in "Bid/RA Awarded" status from
2018 onwards, as shown in the public all-bids list (`bidplus.gem.gov.in/all-bids`) and the
public "View Bid/RA Results" pages:

- bid or RA number, bid type, dates, category, quantity, evaluation type;
- ministry, department and organisation of the buyer (not the buyer official);
- for each financially qualified seller: seller name, MSE/MII status, total price and rank;
- the "Estimated Bid Value", where the buyer declared one in the bid document.

**What we use it for.** A statistical model of winning-price ratios and bidder counts, so a
seller can see what range of prices has won similar bids, with the past results shown as
evidence. We would not republish bid documents or reproduce GeM pages.

**What we offer.**

1. Attribution: "Source: Government e-Marketplace (GeM), gem.gov.in" wherever the data or
   anything derived from it is shown, as your policy requires. Data reproduced accurately,
   never in a misleading or derogatory context.
2. No personal data: we would not collect or store buyer officials' names, email addresses
   or phone numbers. We would remove any seller detail you identify as personal data, and
   act on any removal request from GeM or a seller within 7 days.
3. Rate limits: at most 1 request per second, only between [22:00 and 06:00 IST] or any
   window you set, with a User-Agent that names TenderLens and gives [Email]. We would never
   touch a CAPTCHA or any protected path. A bulk extract or API instead of page requests
   would be our first preference, if GeM can provide one.
4. Data-use terms: we are glad to sign GeM's standard data-sharing terms or an MoU,
   including audit, security and deletion clauses, and to stop and delete the data if
   permission is withdrawn.
5. Reciprocity: aggregate findings (for example competition levels by category and state)
   shared with GeM at no cost.

We would be grateful for permission in writing, or for the name of the officer who handles
data-sharing requests. We are happy to meet or present the use case.

Yours faithfully,

[Founder name]
[Designation], [Company]
[Address] · [Email] · [Phone]
[Date]

---

## B. Department of Expenditure (PPD) and NIC: AOC data under an MoU

**To:**
1. The Joint Secretary, Procurement Policy Division, Department of Expenditure, Ministry of
   Finance, Government of India, [address from doe.gov.in]
2. The Director General, National Informatics Centre, Ministry of Electronics and IT,
   [address from nic.in] (attention: eProcurement / GePNIC and CPPP division)

**Subject:** Proposal for bulk or API access to CPPP and GePNIC Award-of-Contract data under an MoU

Dear Sir or Madam,

[Company] ([CIN]) runs TenderLens ([Website]), which collects tender notices from the CPPP
and 35 GePNIC portals and helps contractors, especially MSEs, decide which tenders to bid
for and at what price.

Rule 159(i) of the General Financial Rules 2017 makes it mandatory for Ministries and
Departments, their attached and subordinate offices and autonomous bodies "to publish their
tender enquiries, corrigenda thereon and details of bid awards on the Central Public
Procurement Portal (CPPP)". Award details are therefore already public by rule. They can,
however, only be read one search at a time behind a CAPTCHA ("Result of Tenders",
"Tenders Status", "Tenders in Archive"), and the CPPP copyright policy asks for the owning
department's permission before reuse. We do not get around CAPTCHAs, so we are asking
for a lawful route instead.

**Request.** Bulk files or an API, under an MoU, for Award-of-Contract records on the CPPP
and on GePNIC portals (central and state), from [2011] onwards and updated [daily/weekly]:

- tender ID, reference number, organisation chain, tender value as published;
- AOC date, contract value, number of bids received (and technically qualified, if held);
- selected bidder;
- where held: the financial bid opening summary (each bidder's quoted price).

**Why it serves the transparency aim.** Machine-readable award data lets bidders price
realistically, which favours competition and fewer abnormally low or single bids, the
outcome the Public Procurement policy seeks. The same data supports the Open Contracting
Data Standard (OCDS), in which TenderLens already exports tender notices.

**What we offer under the MoU.**

1. Use limited to the fields above; attribution to CPPP/GePNIC and the owning department on
   every display.
2. No personal data beyond what the portal itself publishes; removal of any field or record
   on request within 7 days.
3. Any rate limit or access window NIC sets, a named User-Agent and IP range, and security
   controls (encryption, access logs, deletion on termination) as NIC specifies.
4. Free reporting back to DoE: competition indicators by organisation and state (bids per
   tender, single-bid share, award-to-estimate ratios), and an OCDS publication of the
   award data if the Department wishes.
5. Any fee, audit or review that the Department considers appropriate.

We would be glad to present the proposal and to draft the MoU text for your review.

Yours faithfully,

[Founder name]
[Designation], [Company]
[Address] · [Email] · [Phone]
[Date]

---

## C. RTI application (Right to Information Act 2005, section 6)

Use while request B is pending, one department and period at a time. RTI rights belong to
citizens (section 3): the founder files in their own name as an Indian citizen, not in the
company's name. For central public authorities file online at `rtionline.gov.in` (fee Rs 10);
for state authorities, by post to the state Public Information Officer with the state's fee
(Indian Postal Order or demand draft). Reply is due within 30 days (section 7(1)); first
appeal within 30 days of the reply or of the deadline (section 19(1)).

> **To:** The Central / State Public Information Officer, [Department or office, e.g.
> "Office of the Chief Engineer, Public Works Department, Raipur"], [Address]
>
> **Subject:** Application under section 6(1) of the Right to Information Act, 2005
>
> 1. **Name of applicant:** [Founder name]
> 2. **Address for correspondence:** [Address]; email: [Email]; phone: [Phone]
> 3. **Particulars of information sought.** For every tender for which a contract was
>    awarded by [Department / division / circle] between [DD-MM-YYYY] and [DD-MM-YYYY],
>    whether through e-procurement ([portal, e.g. eproc.cgstate.gov.in]) or otherwise:
>    1. tender ID and reference number, name of work, and the estimated cost put to tender;
>    2. date of award of contract (AOC) and the contract value;
>    3. the number of bids received and the number found technically qualified;
>    4. the names of the bidders whose financial bids were opened and the amount quoted by
>       each (the financial bid opening summary or comparative statement);
>    5. the name of the bidder to whom the contract was awarded.
> 4. **Form.** Please provide the information in electronic form (CSV or Excel by email,
>    or on a CD), as permitted by section 7(9). Where a record exists only on paper,
>    certified copies are requested.
> 5. **Note.** Details of bid awards are required to be published on the CPPP under Rule 159
>    of the General Financial Rules 2017, and the contracts above have already been awarded.
>    The information is therefore not covered by the commercial-confidence exemption in
>    section 8(1)(d). If any part is held to be exempt, please provide the rest under
>    section 10 (severability).
> 6. **Fee.** The application fee of Rs [10] is paid by [IPO / DD / online payment, number
>    and date]. I am / am not a Below Poverty Line card holder.
> 7. **Declaration.** I am a citizen of India.
>
> Place: [City] Date: [Date] Signature: ____________

---

## D. Researchers holding bid-level PMGSY data: licence for commercial use

Send as two separate emails (one per research team), from [Email].

**To:** Dr Jonathan Lehne (Paris School of Economics; corresponding author), Prof. Jacob N.
Shapiro (Princeton University), Prof. Oliver Vanden Eynde (Paris School of Economics)
**Subject:** Licence request for the PMGSY tender data behind "Tender competitiveness and project performance in India's PMGSY scheme"

Dear Dr Lehne, Prof. Shapiro and Prof. Vanden Eynde,

I am the founder of [Company], which runs TenderLens ([Website]), a tender-intelligence
service for Indian contractors. Your work on PMGSY tenders (IGC working paper
S-89447-INC-1, February 2019, and "Building connections: Political corruption and road
construction in India") uses bid-level data from pmgsytenders.gov.in for Bihar, Jharkhand,
Odisha, Uttar Pradesh and West Bengal (2008-2016) and SRRDA data for Chhattisgarh
(2001-2017): every bidder, technical results and financial bid amounts.

We are building a model that tells a contractor what range of prices has won comparable
public works, with honest uncertainty. Public bid-level data for Indian works is very
scarce, and yours is the most complete we know of. We would like to ask:

1. whether you could license the bid-level dataset (or the parts you are free to share) to
   [Company] for **commercial use**, on terms you set;
2. if you cannot, who holds the rights (the State Rural Roads Development Agencies, NRIDA
   or the IGC) and whom we should ask.

Our proposed terms: use only to train and evaluate statistical models of winning-price
ratios and bidder counts; no redistribution of the raw data; only aggregates or individual
past awards that are already public shown to users; citation of your paper on every page
that uses it; deletion on request; and the training code and model evaluation shared with
you on request. We are happy to sign a data-use agreement and to discuss a fee or a
contribution to your research.

Thank you for considering this.

Kind regards,
[Founder name], [Designation], [Company]
[Email] · [Phone]

**Second email. To:** Sean Lewis-Faupel, Dr Yusuf Neggers, Prof. Benjamin A. Olken, Prof. Rohini Pande
**Subject:** Commercial-use licence for the openICPSR replication package E114617V1 (e-procurement and PMGSY)

Dear authors,

I am the founder of [Company], which runs TenderLens ([Website]), a tender-intelligence
service for Indian contractors. Your replication package for "Can Electronic Procurement
Improve Infrastructure Provision? Evidence from Public Works in India and Indonesia"
(openICPSR project E114617, version V1; NBER working paper 20344) covers about 35,600 PMGSY
contracts in 27 states from January 2000 to August 2009, with estimated cost, contract
value and final payment, and bid counts for Andhra Pradesh, Chhattisgarh, Karnataka and
Uttar Pradesh.

We could not confirm that the package's openICPSR terms allow commercial use, so we have
not downloaded or used it. We would like to ask whether you, or the data's original
owners, could grant [Company] a licence for commercial use of the India part, on the
following terms: use only to train and evaluate models of winning-price-to-estimate ratios
and bidder counts; no redistribution; citation of your paper wherever results based on it
are shown; deletion on request; and anything else you require. If the rights sit with
NRIDA or the state agencies, we would be grateful for a pointer to the right contact.

Kind regards,
[Founder name], [Designation], [Company]
[Email] · [Phone]

---

## Tracking

| Letter | Sent on | To (name, email or address) | Reference / RTI no. | Reply due | Outcome |
|---|---|---|---|---|---|
| A GeM SPV | | | | | |
| B DoE PPD | | | | | |
| B NIC | | | | | |
| C RTI [department] | | | | 30 days | |
| D Lehne et al. | | | | | |
| D Lewis-Faupel et al. | | | | | |

When a permission arrives, record its scope and conditions in `docs/SOURCE_NOTES.md`
("Award data") before any adapter is built, and set the adapter's `license` text to match.
