//Custom cursor
//(() => { 
//   const cursor = document.querySelector('.cursor');
//   document.addEventListener('mousemove', e => {
//      cursor.setAttribute('style', `top:  ${e.pageY - 25}px; left: ${e.pageX - 25}px;`);
//   });
//   document.addEventListener('click', () => { 
//      cursor.classList.add('cursor--expand');
//      setTimeout(() => {
//         cursor.classList.remove('cursor--expand');
//      }, 500);
//   });
//})();




// 1. Select the specific parent section
const contactSection = document.getElementById('contact');

// 2. Select the specific target element ONLY inside the contact section
const targetIcon = contactSection ? contactSection.querySelector('.icon') : null;

// Ensure both elements exist before proceeding
if (contactSection && targetIcon) {
    // 3. Define the observer options
    const options = {
      root: null, // Use the viewport as the observing container
      threshold: 0.5, // Trigger when 50% of the #contact section is visible
      rootMargin: "0px"
    };

    // 4. Define the callback function that runs on intersection change
    const observer = new IntersectionObserver((entries, observer) => {
      entries.forEach(entry => {
        // entry.isIntersecting is TRUE when the section is visible
        if (entry.isIntersecting) {
          // Add the class when the section is on screen
          targetIcon.classList.add('active');
        } else {
          // Remove the class when the section is off screen
          targetIcon.classList.remove('active');
        }
      });
    }, options);

    // 5. Tell the observer to watch the #contact section
    observer.observe(contactSection);
}



document.addEventListener('DOMContentLoaded', function () {
  const sliderElement = document.getElementById('my-slider');

  if (sliderElement) {
    new Splide(sliderElement, {
      // 1. Set the number of visible slides
      perPage: 4, 
      
      // 2. Disable the navigation buttons (arrows)
      arrows: false, 
      
      // Recommended: Auto-sliding options
      type: 'loop',      // Make it loop infinitely
      autoplay: true,    // Enable automatic sliding
      interval: 4000,
      gap:10,    // Slide every 4 seconds
      
      // Optional: Set how many slides to move per transition
      perMove: 1, 
      
      // Optional: Disable dots/pagination if only auto-slide is wanted
      pagination: false, 

      // Optional: Add responsiveness for mobile devices
      breakpoints: {
        640: { // When viewport is 640px or less
          perPage: 1, // Show only 1 slide on mobile
          arrows: false,
          pagination: false,
        },
        820:{
            perPage: 2,
        },
        1000: { // When viewport is 992px or less
          perPage: 3, // Show 2 slides on tablets
        }
      }
    }).mount();
  }
});