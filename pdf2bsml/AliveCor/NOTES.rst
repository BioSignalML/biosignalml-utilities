::

    >>> import pypdf
    >>> x = pypdf.PdfReader('t.pdf')
    >>> p = x.page[0]
    >>> p
    {'/Parent': IndirectObject(3, 0), '/Contents': IndirectObject(4, 0), '/Type': '/Page', '/Resources': IndirectObject(6, 0), '/MediaBox': [0, 0, 595.27600, 841.89000]}
    >>> p.mediaBox
    RectangleObject([0, 0, 595.27600, 841.89000])
    >>> p.cropBox
    RectangleObject([0, 0, 595.27600, 841.89000])

    ## A4 = 21.0cm x 29.7cm


    >>> c = p.get_contents()

    >>> d = c.get_data()
    >>> type(d)
    <type 'str'>
    >>> len(d)
    184597
    >>> d[0:20]
    'q Q q /Perceptual ri'


    >>> t = p.extract_text()
    >>> len(t)
    330
    >>> t
    u'Patient:\nPeter Hunter, 30/07/48 (66yrs)\nRecorded:Wednesday, 15 July 2015 11:22:43\nHeart Rate:\n57 bpmDuration:\n30sFinding byAliveCor:Normal\n(c) Copyright 2012-2014, AliveCor Inc, AliveECG v2.2.2.0, Report v2.3.1,  UUID: B4EF3C1C-73D2-4088-90F8-620242430F92\nPage 1 of 1\nEnhanced Filter, Mains filter: 50Hz    Scale: 25mm/s, 10mm/mV\n'
