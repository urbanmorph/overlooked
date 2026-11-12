// The same place on yellide's sister sites, for a state's place pages (lib/place_page.js): the air, heat and
// warnings now in its main cities on mugilu (mugilu.live/c/<slug>), and its city ward maps on bharatlas
// (bharatlas.com/view/<layer>). Plain links, so readers and search engines follow them. The cities are the state's
// capital and best-known cities, as mugilu names them (some are districts: Dakshina Kannada for Mangaluru); every
// slug was checked against mugilu.live/places, and the ward maps against bharatlas, on 12 Nov 2026.

/** yellide state slug -> [[name, mugilu slug]], the most visited first. */
export const MUGILU = {
  "andaman-nicobar": [["South Andamans","south-andamans"],["North And Middle Andaman","north-and-middle-andaman"],["Nicobars","nicobars"]],
  "andhra-pradesh": [["Visakhapatnam","visakhapatnam"],["Guntur","guntur"],["Tirupati","tirupati"],["Kurnool","kurnool"]],
  "arunachal-pradesh": [["Papum Pare","papum-pare"],["Tawang","tawang"],["East Siang","east-siang"]],
  "assam": [["Guwahati","guwahati"],["Dibrugarh","dibrugarh"],["Cachar","cachar"],["Jorhat","jorhat"]],
  "bihar": [["Patna","patna"],["Gaya","gaya"],["Bhagalpur","bhagalpur"],["Muzaffarpur","muzaffarpur"]],
  "chandigarh": [["Chandigarh","chandigarh"]],
  "chhattisgarh": [["Raipur","raipur"],["Bilaspur","bilaspur-chhattisgarh"],["Durg","durg"],["Bastar","bastar"]],
  "dadra-nagar-haveli-daman-diu": [["Daman","daman"],["Diu","diu"],["Dadra And Nagar Haveli","dadra-and-nagar-haveli"]],
  "delhi": [["Delhi","delhi"],["New Delhi","new-delhi"]],
  "goa": [["North Goa","north-goa"],["South Goa","south-goa"]],
  "gujarat": [["Ahmedabad","ahmedabad"],["Surat","surat"],["Vadodara","vadodara"],["Rajkot","rajkot"]],
  "haryana": [["Gurugram","gurugram"],["Faridabad","faridabad"],["Ambala","ambala"],["Hisar","hisar"]],
  "himachal-pradesh": [["Shimla","shimla"],["Kangra","kangra"],["Kullu","kullu"],["Mandi","mandi"]],
  "jammu-kashmir": [["Srinagar","srinagar"],["Jammu","jammu"],["Anantnag","anantnag"],["Baramulla","baramulla"]],
  "jharkhand": [["Ranchi","ranchi"],["Dhanbad","dhanbad"],["Bokaro","bokaro"]],
  "karnataka": [["Bengaluru","bengaluru"],["Mysuru","mysuru"],["Dakshina Kannada","dakshina-kannada"],["Dharwad","dharwad"]],
  "kerala": [["Thiruvananthapuram","thiruvananthapuram"],["Kochi","kochi"],["Kozhikode","kozhikode"],["Thrissur","thrissur"]],
  "ladakh": [["Leh Ladakh","leh-ladakh"],["Kargil","kargil"]],
  "lakshadweep": [["Lakshadweep District","lakshadweep-district"]],
  "madhya-pradesh": [["Bhopal","bhopal"],["Indore","indore"],["Jabalpur","jabalpur"],["Gwalior","gwalior"]],
  "maharashtra": [["Mumbai","mumbai"],["Pune","pune"],["Nagpur","nagpur"],["Nashik","nashik"]],
  "manipur": [["Imphal West","imphal-west"],["Imphal East","imphal-east"],["Churachandpur","churachandpur"]],
  "meghalaya": [["East Khasi Hills","east-khasi-hills"],["West Garo Hills","west-garo-hills"],["West Jaintia Hills","west-jaintia-hills"]],
  "mizoram": [["Aizawl","aizawl"],["Lunglei","lunglei"]],
  "nagaland": [["Kohima","kohima"],["Dimapur","dimapur"]],
  "odisha": [["Bhubaneswar","bhubaneswar"],["Cuttack","cuttack"],["Puri","puri"],["Sambalpur","sambalpur"]],
  "puducherry": [["Pondicherry","pondicherry"],["Karaikal","karaikal"]],
  "punjab": [["Ludhiana","ludhiana"],["Amritsar","amritsar"],["Jalandhar","jalandhar"],["Patiala","patiala"]],
  "rajasthan": [["Jaipur","jaipur"],["Jodhpur","jodhpur"],["Udaipur","udaipur"],["Kota","kota"]],
  "sikkim": [["Gangtok","gangtok"]],
  "tamil-nadu": [["Chennai","chennai"],["Coimbatore","coimbatore"],["Madurai","madurai"],["Tiruchirappalli","tiruchirappalli"]],
  "telangana": [["Hyderabad","hyderabad"],["Warangal","warangal"],["Karimnagar","karimnagar"],["Nizamabad","nizamabad"]],
  "tripura": [["West Tripura","west-tripura"]],
  "uttar-pradesh": [["Lucknow","lucknow"],["Kanpur","kanpur"],["Varanasi","varanasi"],["Agra","agra"]],
  "uttarakhand": [["Dehradun","dehradun"],["Haridwar","haridwar"],["Nainital","nainital"],["Almora","almora"]],
  "west-bengal": [["Kolkata","kolkata"],["Darjeeling","darjeeling"],["Paschim Bardhaman","paschim-bardhaman"]],
};

/** yellide state slug -> [[city, bharatlas ward layer]]. */
export const WARD_MAPS = {
  "gujarat": [["Ahmedabad","wards_ahmedabad"],["Surat","wards_surat"],["Vadodara","wards_vadodara"]],
  "maharashtra": [["Mumbai","wards_mumbai"],["Pune","wards_pune"],["Pimpri-Chinchwad","wards_pcmc"],["Thane","wards_thane"],["Navi Mumbai","wards_navi_mumbai"]],
  "delhi": [["Delhi","wards_delhi"]],
  "karnataka": [["Bengaluru","wards_bengaluru_gba"],["Mysuru","wards_mysuru"]],
  "telangana": [["Hyderabad","wards_hyderabad"]],
  "tamil-nadu": [["Chennai","wards_chennai"],["Coimbatore","wards_coimbatore"],["Madurai","wards_madurai"]],
  "west-bengal": [["Kolkata","wards_kolkata"]],
  "odisha": [["Bhubaneswar","wards_bhubaneshwar"]],
  "madhya-pradesh": [["Indore","wards_indore"],["Bhopal","wards_bhopal"]],
  "rajasthan": [["Jaipur","wards_jaipur"]],
  "haryana": [["Gurugram","wards_gurugram"],["Faridabad","wards_faridabad"]],
  "chandigarh": [["Chandigarh","wards_chandigarh"]],
  "kerala": [["Kochi","wards_kochi"]],
  "andhra-pradesh": [["Visakhapatnam","wards_vizag"],["Vijayawada","wards_vijayawada"]],
  "assam": [["Guwahati","wards_guwahati"]],
  "uttar-pradesh": [["Lucknow","wards_lucknow"],["Kanpur","wards_kanpur"]],
  "bihar": [["Patna","wards_patna"]],
};

export const mugiluUrl = slug => `https://mugilu.live/c/${slug}`;
export const wardMapUrl = layer => `https://bharatlas.com/view/${layer}`;
